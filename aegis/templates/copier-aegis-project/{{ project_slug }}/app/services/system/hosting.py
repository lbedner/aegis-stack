"""Where the app runs, and where it can, as Overseer shows it in htmx and
Flet alike.

``running_on()``: the cloud this server is on, read from that cloud's own
metadata service at 169.254.169.254, which every one of them answers on the
server itself and nowhere else. Asked once per process (a server does not
move); nothing answering is ``Local`` before any deploy, ``Self-hosted``
after. ``deploys_to()``: where this project deploys to, from ``aegis
deploy-provision``'s record in ``.aegis/deploy.yml``, which stays on the
machine you deploy from (it is never synced to the server). ``providers()``:
the providers ``aegis`` knows, and what it can do on each, from
``providers.json`` beside this file: the one provider table, which the
``aegis`` CLI reads too, out of the template it ships. No UI framework
imports.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.core import exposure
from app.core.brand_icons import favicon_url

METADATA = "http://169.254.169.254"
PROBE_SECONDS = 0.5  # a link-local answer is instant; off a cloud, nothing is
DEPLOY_CONFIG = Path(".aegis/deploy.yml")


@dataclass(frozen=True)
class Provider:
    key: str
    name: str
    domain: str | None  # for its logo; None draws its initial
    can: tuple[str, ...]  # what aegis does there: Detect, Deploy, Provision
    command: str
    token: str | None = None  # the environment variable the command reads
    check: str | None = None  # a cheap authenticated GET that tells a token works
    size: str | None = None  # deploy-provision's default, where it provisions
    region: str | None = None
    currency: str | None = None  # what its prices are in
    keys: tuple[str, ...] = ()  # a DNS provider's, where one token will not do

    @property
    def secrets(self) -> tuple[str, ...]:
        """The environment variables (and stored secrets) it is reached with."""
        return (self.token,) if self.token else self.keys

    @property
    def logo(self) -> str | None:
        """Its mark (``domain``'s favicon); None draws its initial."""
        return favicon_url(self.domain) if self.domain else None


PROVIDERS = tuple(
    Provider(**{**p, "can": tuple(p["can"]), "keys": tuple(p.get("keys", ()))})
    for p in json.loads(Path(__file__).with_name("providers.json").read_text())
)
# Each provider by its key (the table's).
BY_KEY = {p.key: p for p in PROVIDERS}


def provider(key: str | None) -> Provider | None:
    """The provider the table names ``key``, or None."""
    return BY_KEY.get(key or "")
# Where aegis creates servers, each with the token it needs; and where it
# names them (a DNS record for a domain of your own).
PROVISIONABLE = tuple(p for p in PROVIDERS if "Provision" in p.can)
DNS = tuple(p for p in PROVIDERS if "DNS" in p.can)

_running: dict[str, Any] | None = None


def _where(
    key: str | None, name: str, facts: list[tuple[str, Any]], console: str | None
) -> dict[str, Any]:
    provider = BY_KEY.get(key or "")
    return {
        "key": key,
        "name": name,
        "logo": provider.logo if provider else None,
        "facts": [
            (label, str(value)) for label, value in facts if value not in (None, "")
        ],
        "console": console,
    }


async def _hetzner(client: httpx.AsyncClient) -> dict[str, Any] | None:
    response = await client.get(f"{METADATA}/hetzner/v1/metadata")
    if response.status_code != 200:
        return None
    meta = yaml.safe_load(response.text) or {}
    return _where(
        "hetzner",
        "Hetzner Cloud",
        [
            ("Location", meta.get("availability-zone")),
            ("Server", meta.get("instance-id")),
            ("IP", meta.get("public-ipv4")),
        ],
        "https://console.hetzner.cloud/",
    )


async def _digitalocean(client: httpx.AsyncClient) -> dict[str, Any] | None:
    response = await client.get(f"{METADATA}/metadata/v1.json")
    if response.status_code != 200:
        return None
    meta = response.json()
    public = (meta.get("interfaces") or {}).get("public") or [{}]
    droplet = meta.get("droplet_id")
    return _where(
        "digitalocean",
        "DigitalOcean",
        [
            ("Location", meta.get("region")),
            ("Server", droplet),
            ("IP", (public[0].get("ipv4") or {}).get("ip_address")),
        ],
        f"https://cloud.digitalocean.com/droplets/{droplet}",
    )


async def _aws(client: httpx.AsyncClient) -> dict[str, Any] | None:
    """IMDSv2: a session token first, then the instance's identity."""
    token = await client.put(
        f"{METADATA}/latest/api/token",
        headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
    )
    if token.status_code != 200:
        return None
    response = await client.get(
        f"{METADATA}/latest/dynamic/instance-identity/document",
        headers={"X-aws-ec2-metadata-token": token.text},
    )
    if response.status_code != 200:
        return None
    meta = json.loads(response.text)
    region, instance = meta.get("region"), meta.get("instanceId")
    return _where(
        "aws",
        "AWS",
        [
            ("Location", meta.get("availabilityZone")),
            ("Server", instance),
            ("Type", meta.get("instanceType")),
        ],
        f"https://{region}.console.aws.amazon.com/ec2/home?region={region}"
        f"#InstanceDetails:instanceId={instance}",
    )


PROBES: tuple[Callable[[httpx.AsyncClient], Awaitable[dict[str, Any] | None]], ...] = (
    _hetzner,
    _digitalocean,
    _aws,
)


async def running_on(
    *, transport: httpx.AsyncBaseTransport | None = None
) -> dict[str, Any]:
    """``{"key", "name", "logo", "facts", "console"}`` for this server."""
    global _running
    if _running is None:
        _running = await _detect(transport)
    return _running


async def _detect(transport: httpx.AsyncBaseTransport | None) -> dict[str, Any]:
    async def ask(
        probe: Callable[[httpx.AsyncClient], Awaitable[dict[str, Any] | None]],
        client: httpx.AsyncClient,
    ) -> dict[str, Any] | None:
        try:
            return await probe(client)
        except (httpx.HTTPError, ValueError, yaml.YAMLError):
            return None  # not this cloud, or no cloud at all

    async with httpx.AsyncClient(timeout=PROBE_SECONDS, transport=transport) as client:
        found = await asyncio.gather(*(ask(probe, client) for probe in PROBES))
    for where in found:
        if where is not None:
            return where
    name = "Self-hosted" if exposure.deployed() else "Local"
    return _where(None, name, [], None)


def deploy_config(path: Path = DEPLOY_CONFIG) -> dict[str, Any]:
    """``.aegis/deploy.yml`` (the server, the provision record), or nothing
    where there is none (on the server, or before any deploy)."""
    return (yaml.safe_load(path.read_text()) or {}) if path.is_file() else {}


def provision_record(path: Path = DEPLOY_CONFIG) -> dict[str, Any]:
    """The provisioned server's record in ``.aegis/deploy.yml``, or nothing."""
    return deploy_config(path).get("provision") or {}


def deploys_to(path: Path = DEPLOY_CONFIG) -> dict[str, Any] | None:
    """Where this project deploys to: the provisioned server (its record),
    else the server ``aegis deploy-init`` named, by its address; None where
    there is neither (on the server, or before either)."""
    config = deploy_config(path)
    record = config.get("provision") or {}
    key = record.get("provider")
    provider = BY_KEY.get(key or "")
    if provider is None:
        box = config.get("server") or {}
        if not box.get("host"):
            return None
        facts = [("User", box.get("user")), ("Path", box.get("path"))]
        return _where(None, box["host"], facts, None)
    return _where(
        key,
        provider.name,
        [
            ("Location", record.get("region")),
            ("Size", record.get("size")),
            ("Server", record.get("server_id")),
            ("Domain", record.get("domain")),
            ("IP", record.get("ipv4")),
        ],
        None,
    )


def providers(current: str | None) -> list[dict[str, Any]]:
    """Every place it can run as a card (a DNS provider only names it):
    what aegis can do there, the command and token to start, and whether
    it is the one in use (``current``)."""
    return [
        {
            "key": p.key,
            "name": p.name,
            "logo": p.logo,
            "can": list(p.can),
            "command": p.command,
            "token": p.token,
            "current": p.key == current,
        }
        for p in PROVIDERS
        if p not in DNS
    ]
