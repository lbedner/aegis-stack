"""Where the app runs, and where it can, as Overseer shows it in htmx and
Flet alike.

``running_on()``: the cloud this server is on, read from that cloud's own
metadata service at 169.254.169.254, which every one of them answers on the
server itself and nowhere else. Asked once per process (a server does not
move); nothing answering is ``Local`` before any deploy, ``Self-hosted``
after. ``deploys_to()``: where this project deploys to, from ``aegis
deploy-provision``'s record in ``.aegis/deploy.yml``, which stays on the
machine you deploy from (it is never synced to the server). ``providers()``:
the providers ``aegis`` knows, and what it can do on each. No UI framework
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

from app.core.brand_icons import favicon_url
from app.core.config import settings

METADATA = "http://169.254.169.254"
PROBE_SECONDS = 0.5  # a link-local answer is instant; off a cloud, nothing is
DEPLOY_CONFIG = Path(".aegis/deploy.yml")
LOCAL = "dev"  # BUILD_ID before any deploy stamps it


@dataclass(frozen=True)
class Provider:
    key: str
    name: str
    domain: str | None  # for its logo; None draws its initial
    can: tuple[str, ...]  # what aegis does there: Detect, Deploy, Provision
    command: str
    token: str | None = None  # the environment variable the command reads


PROVIDERS = (
    Provider(
        "hetzner",
        "Hetzner Cloud",
        "hetzner.com",
        ("Detect", "Deploy", "Provision"),
        "aegis deploy-provision --provider hetzner",
        "HCLOUD_TOKEN",
    ),
    Provider(
        "digitalocean",
        "DigitalOcean",
        "digitalocean.com",
        ("Detect", "Deploy"),
        "aegis deploy",
    ),
    Provider("aws", "AWS", "aws.amazon.com", ("Detect", "Deploy"), "aegis deploy"),
    Provider("server", "Any server", None, ("Deploy",), "aegis deploy"),
)
_BY_KEY = {p.key: p for p in PROVIDERS}

_running: dict[str, Any] | None = None


def _where(
    key: str | None, name: str, facts: list[tuple[str, Any]], console: str | None
) -> dict[str, Any]:
    provider = _BY_KEY.get(key or "")
    return {
        "key": key,
        "name": name,
        "logo": favicon_url(provider.domain) if provider and provider.domain else None,
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
    name = "Local" if settings.BUILD_ID == LOCAL else "Self-hosted"
    return _where(None, name, [], None)


def deploys_to(path: Path = DEPLOY_CONFIG) -> dict[str, Any] | None:
    """Where this project deploys to, from the provision record, or None
    where there is no record (on the server, or before provisioning)."""
    if not path.is_file():
        return None
    record = (yaml.safe_load(path.read_text()) or {}).get("provision") or {}
    key = record.get("provider")
    provider = _BY_KEY.get(key or "")
    if provider is None:
        return None
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
    """Every provider as a card: what aegis can do there, the command and
    token to start, and whether it is the one in use (``current``)."""
    return [
        {
            "key": p.key,
            "name": p.name,
            "logo": favicon_url(p.domain) if p.domain else None,
            "can": list(p.can),
            "command": p.command,
            "token": p.token,
            "current": p.key == current,
        }
        for p in PROVIDERS
    ]
