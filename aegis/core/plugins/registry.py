"""The public plugin directory at aegis-stack.io, read as JSON.

``GET /api/v1/plugins`` is the contract the directory publishes for this
command: every package whose wheel has been shown to declare an
``aegis.plugins`` entry point, with stable field names. Read-only and
unauthenticated; ``aegis`` never installs anything from it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ... import __version__

SITE_URL = "https://aegis-stack.io"
REGISTRY_URL = f"{SITE_URL}/api/v1/plugins"
TIMEOUT_SECONDS = 10.0


class RegistryError(Exception):
    """The directory could not be reached or answered with something unusable."""


@dataclass(frozen=True)
class RegistryPlugin:
    """One directory listing: what ``aegis plugins search`` shows."""

    name: str
    """PyPI distribution, what ``pip install`` takes."""
    install_name: str
    """What ``aegis add`` takes."""
    summary: str
    latest_version: str
    verified: bool
    aegis_version: str
    detail_url: str

    @classmethod
    def from_json(cls, item: dict[str, Any]) -> RegistryPlugin:
        detail = str(item.get("detail_url") or "")
        return cls(
            name=str(item["name"]),
            install_name=str(item["install_name"]),
            summary=str(item.get("summary") or ""),
            latest_version=str(item.get("latest_version") or ""),
            verified=bool(item.get("verified")),
            aegis_version=str(item.get("aegis_version") or ""),
            detail_url=f"{SITE_URL}{detail}" if detail.startswith("/") else detail,
        )


def search_registry(keyword: str = "") -> list[RegistryPlugin]:
    """Plugins in the directory matching ``keyword`` (name or summary).

    Raises:
        RegistryError: when the directory is unreachable or its answer is
            not the documented shape.
    """
    url = f"{REGISTRY_URL}?{urlencode({'q': keyword})}" if keyword else REGISTRY_URL
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": f"aegis-stack/{__version__}",
        },
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.load(response)
        return [RegistryPlugin.from_json(item) for item in payload["plugins"]]
    except (URLError, TimeoutError, OSError) as e:
        raise RegistryError(f"could not reach {SITE_URL}: {e}") from None
    except (ValueError, KeyError, TypeError) as e:
        raise RegistryError(f"unexpected answer from {REGISTRY_URL}: {e}") from None
