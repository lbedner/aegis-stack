"""
``aegis deploy-provision`` and ``aegis deploy-destroy``.

Creates a server in the user's own Hetzner account, points a name at it and
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

import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from ..cli import brand
from ..core.provision.cloudflare import API_URL as CLOUDFLARE_API
from ..core.provision.cloudflare import CloudflareDNS
from ..core.provision.hetzner import API_URL as HETZNER_API
from ..core.provision.hetzner import HetznerClient, cloud_init_user_data
from ..core.provision.http import ProvisionError, json_requester, mask_token
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
)
from .ingress import enable_tls, known_email

PROVIDERS = ("hetzner",)
HCLOUD_TOKEN_ENV = "HCLOUD_TOKEN"
CLOUDFLARE_TOKEN_ENV = "CLOUDFLARE_API_TOKEN"
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
    """Hetzner names must be valid hostnames: no underscores, lower case."""
    return re.sub(r"[^a-z0-9-]+", "-", project_name.lower()).strip("-")


def _persist(root: Path, config: dict[str, Any], record: dict[str, Any]) -> None:
    config["provision"] = record
    _save_deploy_config(config, str(root))


def _require(ok: bool, key: str, **kwargs: Any) -> None:
    if not ok:
        raise ProvisionError(t(key, **kwargs))


def _cloud_init_ok(ip: str) -> bool:
    """Block until first-boot setup finishes; True unless it failed."""
    result = _run_remote_capture(ip, "root", "cloud-init status --wait")
    return result.returncode in CLOUD_INIT_OK


def _created_lines(record: dict[str, Any]) -> list[str]:
    """What this record says exists in the user's accounts, one line each."""
    lines = []
    if "server_id" in record:
        lines.append(
            t(
                "provision.created_server",
                id=record["server_id"],
                name=record["server_name"],
                ip=record["ipv4"],
                size=record["size"],
                region=record["region"],
            )
        )
    if "ssh_key_id" in record:
        lines.append(t("provision.created_ssh_key", id=record["ssh_key_id"]))
    if "dns" in record:
        lines.append(t("provision.created_dns", hostname=record["domain"]))
    return lines


def _destroy(
    hcloud: HetznerClient,
    dns: CloudflareDNS | None,
    root: Path,
    config: dict[str, Any],
    record: dict[str, Any],
) -> None:
    """Delete everything the record lists, then mark it destroyed."""
    if "dns" in record and dns is not None:
        dns.delete_record(record["dns"]["zone_id"], record["dns"]["record_id"])
    if "server_id" in record:
        hcloud.delete_server(record["server_id"])
    if "ssh_key_id" in record:
        hcloud.delete_ssh_key(record["ssh_key_id"])
    record["status"] = "destroyed"
    # A recycled IP may become someone else's box; stop deploying to it.
    if (config.get("server") or {}).get("host") == record.get("ipv4"):
        config.pop("server", None)
        config.pop("domain", None)
    _persist(root, config, record)


def _point_name(
    dns: CloudflareDNS | None, record: dict[str, Any], persist: Callable[[], None]
) -> str:
    """The Cloudflare name when one was asked for, else an sslip.io name."""
    ip = record["ipv4"]
    if dns is None or not record.get("domain"):
        return sslip_name(ip)
    if "dns" not in record:
        zone_id, record_id = dns.create_a_record(record["domain"], ip)
        record["dns"] = {"zone_id": zone_id, "record_id": record_id}
        persist()
        typer.echo(t("provision.dns_created", hostname=record["domain"], ip=ip))
    return record["domain"]


def _create(
    hcloud: HetznerClient,
    record: dict[str, Any],
    user_data: str,
    public_key: str,
    persist: Callable[[], None],
) -> None:
    """SSH key, then server; each recorded the moment it exists."""
    key_id, created = hcloud.ensure_ssh_key(record["server_name"], public_key)
    if created:
        record["ssh_key_id"] = key_id
        persist()
        typer.echo(t("provision.ssh_key_created", id=key_id))
    server_id, ip = hcloud.create_server(
        record["server_name"], record["size"], record["region"], key_id, user_data
    )
    record.update(server_id=server_id, ipv4=ip)
    persist()
    brand.success(t("provision.server_created", id=server_id, ip=ip))


def _provision(
    hcloud: HetznerClient,
    dns: CloudflareDNS | None,
    root: Path,
    config: dict[str, Any],
    record: dict[str, Any],
    user_data: str,
    public_key: str,
    email: str,
) -> None:
    def persist() -> None:
        _persist(root, config, record)

    if "server_id" not in record:
        _create(hcloud, record, user_data, public_key, persist)
    ip = record["ipv4"]

    typer.echo(t("provision.waiting_running"))
    running = wait_until(
        lambda: hcloud.server_status(record["server_id"]) == "running",
        SERVER_RUNNING_ATTEMPTS,
        SERVER_RUNNING_INTERVAL,
    )
    _require(running, "provision.not_running")
    typer.echo(t("provision.waiting_ssh", ip=ip))
    _require(wait_for_host_key(ip), "provision.ssh_timeout", ip=ip)
    typer.echo(t("provision.waiting_cloud_init"))
    _require(_cloud_init_ok(ip), "provision.cloud_init_failed", ip=ip)

    hostname = _point_name(dns, record, persist)
    typer.echo(t("provision.waiting_dns", hostname=hostname))
    _require(wait_for_dns(hostname, ip), "provision.dns_timeout", hostname=hostname)

    project_name = _get_project_name(str(root))
    config["server"] = {"host": ip, "user": "root", "path": f"/opt/{project_name}"}
    config.setdefault("docker", {"context": f"{project_name}-remote"})
    config["domain"] = hostname
    record["status"] = "ready"
    persist()
    brand.success(t("provision.ready", hostname=hostname))

    # A project generated without TLS has no :443 listener or resolver at
    # all; the name the server just got needs both before the first deploy.
    enable_tls(root, hostname, email)
    deploy_command(
        project_path=str(root),
        build=True,
        backup=True,
        health_check=True,
        rolling=False,
        drain_timeout=ROLLING_DRAIN_TIMEOUT_DEFAULT,
        rollout_timeout=ROLLING_ROLLOUT_TIMEOUT_DEFAULT,
    )


def _on_failure(
    exc: BaseException,
    hcloud: HetznerClient,
    dns: CloudflareDNS | None,
    root: Path,
    config: dict[str, Any],
    record: dict[str, Any],
    yes: bool,
) -> None:
    """Say what exists after a failed run and offer to delete it."""
    if isinstance(exc, ProvisionError):
        brand.error(str(exc), err=True)
    created = _created_lines(record)
    if not created:
        return
    brand.warn(t("provision.partial_title"))
    for line in created:
        typer.echo(f"  {line}")
    if yes or not typer.confirm(t("provision.offer_delete"), default=False):
        typer.echo(t("provision.resume_hint"))
        return
    try:
        _destroy(hcloud, dns, root, config, record)
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


def _confirm_price(hcloud: HetznerClient, record: dict[str, Any], yes: bool) -> None:
    try:
        price = hcloud.monthly_price(record["size"], record["region"])
    except ProvisionError as exc:
        brand.error(str(exc), err=True)
        raise typer.Exit(1) from None
    brand.accent(
        t("provision.price", size=record["size"], region=record["region"], price=price),
        bold=True,
    )
    if not yes and not typer.confirm(t("provision.confirm"), default=False):
        typer.echo(t("provision.cancelled"))
        raise typer.Exit(0)


def deploy_provision_command(
    provider: str = typer.Option(
        "hetzner", "--provider", help=lazy_t("provision.help_opt_provider")
    ),
    size: str = typer.Option("cx23", "--size", help=lazy_t("provision.help_opt_size")),
    region: str = typer.Option(
        "nbg1", "--region", help=lazy_t("provision.help_opt_region")
    ),
    domain: str | None = typer.Option(
        None, "--domain", help=lazy_t("provision.help_opt_domain")
    ),
    ssh_key: str | None = typer.Option(
        None, "--ssh-key", help=lazy_t("provision.help_opt_ssh_key")
    ),
    email: str | None = typer.Option(
        None, "--email", help=lazy_t("provision.help_opt_email")
    ),
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help=lazy_t("common.help_yes")),
) -> None:
    """
    Create a server in your own cloud account and deploy to it.

    Reads HCLOUD_TOKEN (and CLOUDFLARE_API_TOKEN with --domain) from the
    environment. Re-run to resume an interrupted run.

    Examples:
        - aegis deploy-provision
        - aegis deploy-provision --size cx33 --region fsn1
        - aegis deploy-provision --domain app.example.com
        - aegis deploy-provision --email ops@example.com
    """
    if provider not in PROVIDERS:
        brand.error(
            t(
                "provision.unknown_provider",
                provider=provider,
                supported=", ".join(PROVIDERS),
            ),
            err=True,
        )
        raise typer.Exit(1)
    hcloud = HetznerClient(json_requester(HETZNER_API, _token(HCLOUD_TOKEN_ENV)))
    root = _get_project_root(project_path)
    user_data, public_key = _read_inputs(root, ssh_key)
    acme_email = _acme_email(root, email)

    config = _load_deploy_config(str(root)) or {}
    record: dict[str, Any] = config.get("provision") or {}
    if record.get("status") == "ready":
        brand.error(t("provision.already_ready", ip=record.get("ipv4")), err=True)
        raise typer.Exit(1)
    resuming = record.get("status") == "provisioning"
    if not resuming:
        record = {
            "provider": provider,
            "server_name": _server_name(_get_project_name(str(root))),
            "region": region,
            "size": size,
            "domain": domain,
            "status": "provisioning",
        }
    dns = None
    if record.get("domain"):
        dns = CloudflareDNS(
            json_requester(CLOUDFLARE_API, _token(CLOUDFLARE_TOKEN_ENV))
        )

    if resuming:
        brand.accent(t("provision.resuming", name=record["server_name"]), bold=True)
    else:
        _confirm_price(hcloud, record, yes)

    try:
        _provision(hcloud, dns, root, config, record, user_data, public_key, acme_email)
    except (Exception, KeyboardInterrupt) as exc:
        _on_failure(exc, hcloud, dns, root, config, record, yes)
        if isinstance(exc, ProvisionError | typer.Exit):
            raise typer.Exit(1) from None
        raise


def deploy_destroy_command(
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
) -> None:
    """
    Delete the provisioned server, its DNS record and its SSH key.

    Asks you to type the server name to confirm.

    Examples:
        - aegis deploy-destroy
    """
    root = _get_project_root(project_path)
    config = _load_deploy_config(str(root)) or {}
    record: dict[str, Any] = config.get("provision") or {}
    if not record or record.get("status") == "destroyed":
        brand.error(t("provision.nothing_to_destroy"), err=True)
        raise typer.Exit(1)
    hcloud = HetznerClient(json_requester(HETZNER_API, _token(HCLOUD_TOKEN_ENV)))
    dns = None
    if "dns" in record:
        dns = CloudflareDNS(
            json_requester(CLOUDFLARE_API, _token(CLOUDFLARE_TOKEN_ENV))
        )

    brand.warn(t("provision.destroy_title"), bold=True)
    for line in _created_lines(record):
        typer.echo(f"  {line}")
    name = record["server_name"]
    typed = typer.prompt(
        t("provision.destroy_confirm", name=name), default="", show_default=False
    )
    if typed.strip() != name:
        brand.error(t("provision.destroy_cancelled"), err=True)
        raise typer.Exit(1)
    try:
        _destroy(hcloud, dns, root, config, record)
    except ProvisionError as exc:
        brand.error(str(exc), err=True)
        typer.echo(t("provision.resume_hint"))
        raise typer.Exit(1) from None
    brand.success(t("provision.destroyed"))
