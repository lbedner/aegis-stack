"""
``aegis deploy-provision`` and ``aegis deploy-destroy``.

Creates a server in the user's own cloud account (any provider in
``core/provision/registry.py``), points a name at it and
hands off to ``aegis deploy``. The box, the bill and the data stay the
user's; tokens are read from the environment at call time and never stored
or printed beyond their last four characters.

The provision record lives under ``provision:`` in ``.aegis/deploy.yml`` and
is written the moment anything billable exists, so an interrupted run can be
resumed (re-run the command) or cleaned up (``aegis deploy-destroy``). Its
``provider`` / ``server_id`` / ``region`` / ``size`` keys are the fields the
DR-06 deploy record gains; when that record lands, ``aegis deploy`` reads
them from here.
"""

import ipaddress
import os
import re
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

import typer

from ..cli import brand
from ..core.provision.http import ProvisionError, json_requester, mask_token
from ..core.provision.provider import (
    DnsClient,
    ProviderClient,
    cloud_init_user_data,
    monthly_price,
)
from ..core.provision.registry import DNS_PROVIDERS, PROVIDERS, DnsProvider, Provider
from ..core.provision.wait import (
    sslip_name,
    wait_for_dns,
    wait_for_host_key,
    wait_until,
)
from ..i18n import lazy_t, t
from .deploy import (
    ROLLING_DRAIN_TIMEOUT_DEFAULT,
    ROLLING_ROLLOUT_TIMEOUT_DEFAULT,
    _get_project_name,
    _get_project_root,
    _load_deploy_config,
    _project_answers,
    _run_remote_capture,
    _save_deploy_config,
    deploy_command,
    refuse_unsafe_env,
)
from .deploy_agent import _protocol
from .deploy_upload import refuse_unless_sqlite, upload_db
from .ingress import enable_tls, known_email

SERVER_RUNNING_ATTEMPTS = 60
SERVER_RUNNING_INTERVAL = 5
# cloud-init exits 2 for "done, with recoverable warnings"; 1 is a failure.
CLOUD_INIT_OK = (0, 2)


def _token(env: str) -> str:
    """Read a provider token from the environment; never echo more than ...abcd."""
    token = os.environ.get(env, "").strip()
    if not token:
        brand.error(t("provision.token_missing", env=env), err=True)
        raise typer.Exit(1)
    typer.echo(t("provision.using_token", env=env, masked=mask_token(token)))
    return token


def _server_name(project_name: str) -> str:
    """Server names must be valid hostnames: no underscores, lower case."""
    return re.sub(r"[^a-z0-9-]+", "-", project_name.lower()).strip("-")


def _persist(root: Path, config: dict[str, Any], record: dict[str, Any]) -> None:
    config["provision"] = record
    _save_deploy_config(config, str(root))


def _step(record: dict[str, Any], key: str) -> None:
    """Where the step bar stands, for the deploy agent (``progress_line``):
    the provision's steps, ``data`` only when ``record`` brings it; nothing
    in a terminal."""
    if os.environ.get(_protocol.PROTOCOL["progress_env"]):
        steps = [
            s for s in _protocol.PROVISION_STEPS if s != "data" or record.get("data")
        ]
        typer.echo(_protocol.progress_line(steps, key))


def _require(ok: bool, key: str, **kwargs: Any) -> None:
    if not ok:
        raise ProvisionError(t(key, **kwargs))


def _cloud_init_ok(ip: str) -> bool:
    """Block until first-boot setup finishes; True unless it failed."""
    result = _run_remote_capture(ip, "root", "cloud-init status --wait")
    return result.returncode in CLOUD_INIT_OK


Known = TypeVar("Known")


def _known(table: dict[str, Known], key: str | None) -> Known:
    """``table``'s entry for ``key``; an unknown one is named, with those
    there are."""
    if key in table:
        return table[key]
    supported = ", ".join(table)
    brand.error(
        t("provision.unknown_provider", provider=key, supported=supported), err=True
    )
    raise typer.Exit(1)


def _provider(key: str | None) -> Provider:
    return _known(PROVIDERS, key)


def _client(provider: Provider) -> ProviderClient:
    return provider.client(json_requester(provider.api_url, _token(provider.token_env)))


def _dns(key: str | None) -> DnsProvider:
    """The DNS provider named (``--dns``), else the first in the table whose
    keys this environment holds; without any, its keys are named."""
    if key is not None:
        return _known(DNS_PROVIDERS, key)
    for spec in DNS_PROVIDERS.values():
        if all(os.environ.get(name, "").strip() for name in spec.secrets):
            return spec
    wanted = " or ".join(" + ".join(p.secrets) for p in DNS_PROVIDERS.values())
    brand.error(t("provision.token_missing", env=wanted), err=True)
    raise typer.Exit(1)


def _connect(spec: DnsProvider) -> tuple[str, DnsClient]:
    """``spec``'s key and its client, its keys from the environment."""
    return spec.key, spec.connect(*(_token(name) for name in spec.secrets))


def _allowlist(value: str | None) -> str | None:
    """``--allowlist`` as comma-separated networks (``203.0.113.9/32``);
    anything else is refused before a server is bought."""
    if not value:
        return None
    try:
        nets = [ipaddress.ip_network(part.strip()) for part in value.split(",")]
    except ValueError:
        brand.error(t("provision.bad_allowlist", value=value), err=True)
        raise typer.Exit(1) from None
    return ",".join(str(net) for net in nets)


def _names_itself(root: Path) -> bool:
    """Whether the project already serves HTTPS and its production compose
    takes the server's name from ``DOMAIN`` in its .env (stamped at
    deploy): then provisioning leaves its files as they are, rather than
    rendering the name (and HTTPS) in."""
    prod = root / "docker-compose.prod.yml"
    tls = _project_answers(root).get("ingress_tls") is True
    return tls and prod.is_file() and "${DOMAIN" in prod.read_text()


def _created_lines(record: dict[str, Any]) -> list[str]:
    """What this record says exists in the user's accounts, one line each."""
    lines = []
    if "server_id" in record:
        lines.append(
            t(
                "provision.created_server",
                id=record["server_id"],
                name=record["server_name"],
                ip=record.get("ipv4") or "?",
                size=record["size"],
                region=record["region"],
            )
        )
    if "firewall_id" in record:
        lines.append(t("provision.created_firewall", id=record["firewall_id"]))
    if "ssh_key_id" in record:
        lines.append(t("provision.created_ssh_key", id=record["ssh_key_id"]))
    if "dns" in record:
        lines.append(t("provision.created_dns", hostname=record["domain"]))
    return lines


def _destroy(
    cloud: ProviderClient,
    dns: tuple[str, DnsClient] | None,
    root: Path,
    config: dict[str, Any],
    record: dict[str, Any],
) -> None:
    """Delete everything the record lists, then mark it destroyed."""
    if "dns" in record and dns is not None:
        dns[1].delete_record(record["dns"]["zone_id"], record["dns"]["record_id"])
    if "firewall_id" in record:
        cloud.delete_firewall(record["firewall_id"])
    if "server_id" in record:
        cloud.delete_server(record["server_id"])
    if "ssh_key_id" in record:
        cloud.delete_ssh_key(record["ssh_key_id"])
    record["status"] = "destroyed"
    # A recycled IP may become someone else's box; stop deploying to it.
    if (config.get("server") or {}).get("host") == record.get("ipv4"):
        config.pop("server", None)
        config.pop("domain", None)
    _persist(root, config, record)


def _point_name(
    dns: tuple[str, DnsClient] | None,
    record: dict[str, Any],
    persist: Callable[[], None],
) -> str:
    """The name asked for, its record made at the DNS provider (``dns``,
    its key and client), else an sslip.io name."""
    ip = record["ipv4"]
    if dns is None or not record.get("domain"):
        return sslip_name(ip)
    if "dns" not in record:
        key, client = dns
        zone_id, record_id = client.create_a_record(record["domain"], ip)
        record["dns"] = {"provider": key, "zone_id": zone_id, "record_id": record_id}
        persist()
        typer.echo(t("provision.dns_created", hostname=record["domain"], ip=ip))
    return record["domain"]


def _create(
    cloud: ProviderClient,
    record: dict[str, Any],
    user_data: str,
    public_key: str,
    persist: Callable[[], None],
) -> None:
    """SSH key, then server; each recorded the moment it exists."""
    key_id, created = cloud.ensure_ssh_key(record["server_name"], public_key)
    if created:
        record["ssh_key_id"] = key_id
        persist()
        typer.echo(t("provision.ssh_key_created", id=key_id))
    record["server_id"] = cloud.create_server(
        record["server_name"], record["size"], record["region"], key_id, user_data
    )
    persist()


def _wait_running(
    cloud: ProviderClient, record: dict[str, Any], persist: Callable[[], None]
) -> str:
    """Wait for the server and record its IP (some clouds give it only now)."""
    typer.echo(t("provision.waiting_running"))
    seen: list[str | None] = []

    def running() -> bool:
        seen.append(cloud.running_ipv4(record["server_id"]))
        return bool(seen[-1])

    _require(
        wait_until(running, SERVER_RUNNING_ATTEMPTS, SERVER_RUNNING_INTERVAL),
        "provision.not_running",
    )
    ip = str(seen[-1])
    if record.get("ipv4") != ip:
        record["ipv4"] = ip
        persist()
        brand.success(t("provision.server_created", id=record["server_id"], ip=ip))
    return ip


def _firewall(
    cloud: ProviderClient, record: dict[str, Any], persist: Callable[[], None]
) -> None:
    """The cloud firewall in front of the server, where the provider makes one."""
    if "firewall_id" in record:
        return
    firewall_id = cloud.create_firewall(record["server_name"], record["server_id"])
    if firewall_id:
        record["firewall_id"] = firewall_id
        persist()
        typer.echo(t("provision.firewall_created", id=firewall_id))


def _provision(
    cloud: ProviderClient,
    dns: tuple[str, DnsClient] | None,
    root: Path,
    config: dict[str, Any],
    record: dict[str, Any],
    user_data: str,
    public_key: str,
    email: str,
) -> None:
    def persist() -> None:
        _persist(root, config, record)

    _step(record, "server")
    if "server_id" not in record:
        _create(cloud, record, user_data, public_key, persist)
    ip = _wait_running(cloud, record, persist)
    _firewall(cloud, record, persist)
    _step(record, "boot")
    typer.echo(t("provision.waiting_ssh", ip=ip))
    _require(wait_for_host_key(ip), "provision.ssh_timeout", ip=ip)
    typer.echo(t("provision.waiting_cloud_init"))
    _require(_cloud_init_ok(ip), "provision.cloud_init_failed", ip=ip)

    _step(record, "dns")
    hostname = _point_name(dns, record, persist)
    typer.echo(t("provision.waiting_dns", hostname=hostname))
    _require(wait_for_dns(hostname, ip), "provision.dns_timeout", hostname=hostname)

    project_name = _get_project_name(str(root))
    config["server"] = {"host": ip, "user": "root", "path": f"/opt/{project_name}"}
    config.setdefault("docker", {"context": f"{project_name}-remote"})
    config["domain"] = hostname
    persist()
    brand.success(t("provision.ready", hostname=hostname))
    _step(record, "deploy")

    # A project generated without TLS has no :443 listener or resolver at
    # all; the name the server just got needs both before the first deploy.
    # One whose files read the name from DOMAIN is left as it is.
    if not _names_itself(root):
        enable_tls(root, hostname, email)
    # No backup: nothing has served here to roll back to, and a rollback
    # would take the failed containers, and why they failed, with it.
    deploy_command(
        project_path=str(root),
        build=True,
        backup=False,
        health_check=True,
        rolling=False,
        drain_timeout=ROLLING_DRAIN_TIMEOUT_DEFAULT,
        rollout_timeout=ROLLING_ROLLOUT_TIMEOUT_DEFAULT,
    )
    # Ready once it serves: a failed first deploy is resumed like any step.
    record["status"] = "ready"
    persist()


def _on_failure(
    exc: BaseException,
    cloud: ProviderClient,
    dns: tuple[str, DnsClient] | None,
    root: Path,
    config: dict[str, Any],
    record: dict[str, Any],
    yes: bool,
) -> None:
    """Say what exists after a failed run and offer to delete it; why it
    stopped stays in the record (the agent's job saying so goes in hours)."""
    if isinstance(exc, ProvisionError):
        brand.error(str(exc), err=True)
    created = _created_lines(record)
    if not created:
        return
    # A ProvisionError's message is written for the user, a deploy's exit
    # (it said why above) as the deploy failing; anything else (a bug,
    # Ctrl-C) by its name only, never what it may carry.
    if isinstance(exc, ProvisionError):
        record["error"] = str(exc)
    elif isinstance(exc, typer.Exit):
        record["error"] = t("provision.first_deploy_failed")
    else:
        record["error"] = type(exc).__name__
    _persist(root, config, record)
    brand.warn(t("provision.partial_title"))
    for line in created:
        typer.echo(f"  {line}")
    if yes or not typer.confirm(t("provision.offer_delete"), default=False):
        typer.echo(t("provision.resume_hint"))
        return
    try:
        _destroy(cloud, dns, root, config, record)
    except ProvisionError as cleanup_exc:
        brand.error(t("provision.cleanup_failed", error=cleanup_exc), err=True)
        typer.echo(t("provision.resume_hint"))
        return
    brand.success(t("provision.cleaned_up"))


# Tried in order when ``--ssh-key`` is not given, as ``ssh`` itself would.
DEFAULT_PUBLIC_KEYS = ("id_ed25519.pub", "id_ecdsa.pub", "id_rsa.pub")


def _default_public_key() -> Path:
    """The first of the user's usual public keys that exists."""
    ssh_dir = Path.home() / ".ssh"
    for name in DEFAULT_PUBLIC_KEYS:
        if (ssh_dir / name).exists():
            return ssh_dir / name
    brand.error(
        t("provision.no_ssh_key", dir=ssh_dir, names=", ".join(DEFAULT_PUBLIC_KEYS)),
        err=True,
    )
    raise typer.Exit(1)


def _acme_email(root: Path, email: str | None) -> str:
    """The address Let's Encrypt registers the certificate to.

    ``--email`` wins, then the project's ``author_email`` unless it is still
    the generated placeholder, which Let's Encrypt refuses. Checked before
    any server exists, so a missing address costs nothing.
    """
    found = email or known_email(_project_answers(root))
    if found:
        return found
    brand.error(t("provision.email_required"), err=True)
    raise typer.Exit(1)


def _read_inputs(root: Path, ssh_key: str | None) -> tuple[str, str]:
    """The setup script as user-data and the public key; fail before any API call."""
    setup_script = root / "scripts" / "server-setup.sh"
    if not setup_script.exists():
        brand.error(t("deploy.setup_script_missing", path=setup_script), err=True)
        raise typer.Exit(1)
    pubkey_path = Path(ssh_key).expanduser() if ssh_key else _default_public_key()
    if not pubkey_path.exists():
        brand.error(t("deploy.pubkey_missing", path=str(pubkey_path)), err=True)
        raise typer.Exit(1)
    return cloud_init_user_data(
        setup_script.read_text()
    ), pubkey_path.read_text().strip()


def _confirm_price(
    cloud: ProviderClient, provider: Provider, record: dict[str, Any], yes: bool
) -> None:
    try:
        price = monthly_price(cloud, record["size"], record["region"])
    except ProvisionError as exc:
        brand.error(str(exc), err=True)
        raise typer.Exit(1) from None
    size, region = record["size"], record["region"]
    price_key = f"provision.price.{provider.key}"
    brand.accent(t(price_key, size=size, region=region, price=price), bold=True)
    confirm = t("provision.confirm", provider=provider.name)
    if not yes and not typer.confirm(confirm, default=False):
        typer.echo(t("provision.cancelled"))
        raise typer.Exit(0)


def _per_provider(field: str) -> str:
    """``hetzner cx23, digitalocean s-1vcpu-2gb``: a default for each provider."""
    return ", ".join(f"{key} {getattr(p, field)}" for key, p in PROVIDERS.items())


class Data(str, Enum):
    """What ``--data`` brings to the new server."""

    LOCAL = "local"  # this machine's database (``aegis deploy-upload-db``)


def deploy_provision_command(
    provider: str | None = typer.Option(
        None,
        "--provider",
        help=lazy_t("provision.help_opt_provider", providers=", ".join(PROVIDERS)),
    ),
    size: str | None = typer.Option(
        None,
        "--size",
        help=lazy_t("provision.help_opt_size", sizes=_per_provider("size")),
    ),
    region: str | None = typer.Option(
        None,
        "--region",
        help=lazy_t("provision.help_opt_region", regions=_per_provider("region")),
    ),
    domain: str | None = typer.Option(
        None, "--domain", help=lazy_t("provision.help_opt_domain")
    ),
    dns_provider: str | None = typer.Option(
        None,
        "--dns",
        help=lazy_t("provision.help_opt_dns", providers=", ".join(DNS_PROVIDERS)),
    ),
    ssh_key: str | None = typer.Option(
        None, "--ssh-key", help=lazy_t("provision.help_opt_ssh_key")
    ),
    email: str | None = typer.Option(
        None, "--email", help=lazy_t("provision.help_opt_email")
    ),
    allowlist: str | None = typer.Option(
        None, "--allowlist", help=lazy_t("provision.help_opt_allowlist")
    ),
    data: Data | None = typer.Option(
        None, "--data", help=lazy_t("provision.help_opt_data")
    ),
    resume: bool = typer.Option(
        False, "--resume", help=lazy_t("provision.help_opt_resume")
    ),
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help=lazy_t("common.help_yes")),
) -> None:
    """
    Create a server in your own cloud account and deploy to it.

    Reads the provider's API token (and, with --domain, the DNS provider's
    keys: CLOUDFLARE_API_TOKEN, or PORKBUN_API_KEY and PORKBUN_SECRET_KEY)
    from the environment; a missing one is named. Re-run to resume an
    interrupted run; --resume only resumes, never starting a new server.

    Examples:
        - aegis deploy-provision
        - aegis deploy-provision --size cx33 --region fsn1
        - aegis deploy-provision --provider digitalocean --region fra1
        - aegis deploy-provision --domain app.example.com
        - aegis deploy-provision --domain app.example.com --dns porkbun
        - aegis deploy-provision --email ops@example.com
        - aegis deploy-provision --allowlist 203.0.113.9/32
        - aegis deploy-provision --data local
        - aegis deploy-provision --resume
    """
    root = _get_project_root(project_path)
    config = _load_deploy_config(str(root)) or {}
    record: dict[str, Any] = config.get("provision") or {}
    if record.get("status") == "ready":
        brand.error(t("provision.already_ready", ip=record.get("ipv4")), err=True)
        raise typer.Exit(1)
    resuming = record.get("status") == "provisioning"
    if resume and not resuming:  # never a new server in its place
        brand.error(t("provision.nothing_to_resume"), err=True)
        raise typer.Exit(1)
    if resuming:
        record.pop("error", None)  # this run's, if it stops again
        # Carried on as first asked: the Overseer's Resume names nothing.
        provider = record["provider"]
        data = data or (Data(record["data"]) if record.get("data") else None)
        email = email or config.get("acme_email")
    provider = provider or "hetzner"
    spec = _provider(provider)
    cloud = _client(spec)
    refuse_unsafe_env(root)  # its deploy would refuse it after the purchase
    if data:
        refuse_unless_sqlite(root)
    user_data, public_key = _read_inputs(root, ssh_key)
    acme_email = _acme_email(root, email)
    admins = _allowlist(allowlist)

    # Stamped into the server's .env at each deploy (``deploy.STAMPED``).
    config["acme_email"] = acme_email
    if admins:
        config["admin_ip_allowlist"] = admins
    if not resuming:
        record = {
            "provider": provider,
            "server_name": _server_name(_get_project_name(str(root))),
            "region": region or spec.region,
            "size": size or spec.size,
            "domain": domain,
            "status": "provisioning",
        }
    if data:
        record["data"] = data.value
    dns = None
    if record.get("domain"):
        made = _protocol.record_dns_provider(record)
        dns = _connect(_dns(made or dns_provider))
        record["dns_provider"] = dns[0]  # a resume's, before the name is made

    if resuming:
        brand.accent(t("provision.resuming", name=record["server_name"]), bold=True)
    else:
        _confirm_price(cloud, spec, record, yes)

    try:
        _provision(cloud, dns, root, config, record, user_data, public_key, acme_email)
    except (Exception, KeyboardInterrupt) as exc:
        _on_failure(exc, cloud, dns, root, config, record, yes)
        if isinstance(exc, ProvisionError | typer.Exit):
            raise typer.Exit(1) from None
        raise
    # The server stands and serves; a failed upload is retried with
    # ``aegis deploy-upload-db``, never a reason to undo the purchase.
    if data:
        _step(record, "data")
        upload_db(root, config["server"])


def deploy_destroy_command(
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
    confirm: str | None = typer.Option(
        None, "--confirm", help=lazy_t("provision.help_opt_confirm")
    ),
) -> None:
    """
    Delete the provisioned server, its DNS record and its SSH key.

    Asks you to type the server name to confirm, or takes it as --confirm.

    Examples:
        - aegis deploy-destroy
        - aegis deploy-destroy --confirm my-app
    """
    root = _get_project_root(project_path)
    config = _load_deploy_config(str(root)) or {}
    record: dict[str, Any] = config.get("provision") or {}
    if not record or record.get("status") == "destroyed":
        brand.error(t("provision.nothing_to_destroy"), err=True)
        raise typer.Exit(1)
    cloud = _client(_provider(record.get("provider")))
    dns = None
    if "dns" in record:
        dns = _connect(_dns(_protocol.record_dns_provider(record)))

    brand.warn(t("provision.destroy_title"), bold=True)
    for line in _created_lines(record):
        typer.echo(f"  {line}")
    name = record["server_name"]
    typed = confirm
    if typed is None:
        typed = typer.prompt(
            t("provision.destroy_confirm", name=name), default="", show_default=False
        )
    if typed.strip() != name:
        brand.error(t("provision.destroy_cancelled"), err=True)
        raise typer.Exit(1)
    try:
        _destroy(cloud, dns, root, config, record)
    except ProvisionError as exc:
        brand.error(str(exc), err=True)
        typer.echo(t("provision.resume_hint"))
        raise typer.Exit(1) from None
    brand.success(t("provision.destroyed"))
