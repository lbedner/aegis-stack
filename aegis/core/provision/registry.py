"""The clouds ``aegis deploy-provision`` can create servers in.

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
from . import digitalocean, hetzner
from .http import Requester
from .provider import ProviderClient

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
