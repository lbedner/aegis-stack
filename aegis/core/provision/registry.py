"""The clouds ``aegis deploy-provision`` can create servers in, and the DNS
providers that can name them.

Provider facts (name, token variable, default size and region, what aegis can
do there) have one home: ``providers.json`` in the project template, beside
the Overseer's ``hosting.py``, which reads it in the generated app. The CLI
reads that same file out of the template shipped inside this package. This
module adds only the code side: which client speaks to which API.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass

from ..component_files import PROJECT_SLUG_PLACEHOLDER, get_template_path
from . import cloudflare, digitalocean, hetzner, porkbun
from .http import Requester, json_requester
from .provider import DnsClient, ProviderClient

FACTS = (
    get_template_path()
    / PROJECT_SLUG_PLACEHOLDER
    / "app"
    / "services"
    / "system"
    / "providers.json"
)
_CLIENTS: dict[str, tuple[str, Callable[[Requester], ProviderClient]]] = {
    "hetzner": (hetzner.API_URL, hetzner.HetznerClient),
    "digitalocean": (digitalocean.API_URL, digitalocean.DigitalOceanClient),
}


@dataclass(frozen=True)
class Provider:
    key: str
    name: str
    token_env: str
    size: str  # default --size
    region: str  # default --region
    currency: str  # what its prices are in
    api_url: str
    client: Callable[[Requester], ProviderClient]


def _load() -> dict[str, Provider]:
    """Every provider the table says aegis can provision on, with its client."""
    return {
        p["key"]: Provider(
            p["key"],
            p["name"],
            p["token"],
            p["size"],
            p["region"],
            p["currency"],
            *_CLIENTS[p["key"]],
        )
        for p in json.loads(FACTS.read_text())
        if "Provision" in p["can"]
    }


PROVIDERS = _load()


@dataclass(frozen=True)
class DnsProvider:
    key: str
    name: str
    secrets: tuple[str, ...]  # the environment variables it is reached with
    connect: Callable[..., DnsClient]  # its client, from those values in order


def _cloudflare(token: str) -> DnsClient:
    return cloudflare.CloudflareDNS(json_requester(cloudflare.API_URL, token))


def _porkbun(api_key: str, secret_key: str) -> DnsClient:
    keys = {"apikey": api_key, "secretapikey": secret_key}
    return porkbun.PorkbunDNS(json_requester(porkbun.API_URL, body=keys))


_DNS_CLIENTS: dict[str, Callable[..., DnsClient]] = {
    "cloudflare": _cloudflare,
    "porkbun": _porkbun,
}


def _load_dns() -> dict[str, DnsProvider]:
    """Every DNS provider the table names, with its client."""
    return {
        p["key"]: DnsProvider(
            p["key"],
            p["name"],
            tuple(p.get("keys") or (p["token"],)),
            _DNS_CLIENTS[p["key"]],
        )
        for p in json.loads(FACTS.read_text())
        if "DNS" in p["can"]
    }


DNS_PROVIDERS = _load_dns()
