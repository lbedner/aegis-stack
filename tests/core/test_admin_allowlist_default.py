"""The admin paths are closed to the public internet unless opened on purpose.

Traefik's ``webserver-admin`` router (``/dashboard``, ``/docs``, ``/redoc``,
``/openapi.json``) sits behind an IP allowlist. Its default was
``0.0.0.0/0``, which admits every address, so every deployed app shipped
those paths open. The default is now loopback and the private ranges:
local development still reaches them (Docker hands Traefik the browser's
requests from a 172.x gateway), and a public deployment opens them only by
setting ``ADMIN_IP_ALLOWLIST``.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
PROJECT = ROOT / "aegis/templates/copier-aegis-project/{{ project_slug }}"
COMPOSE_FILES = [
    "docker-compose.yml.jinja",
    "docker-compose.dev.yml.jinja",
    "docker-compose.prod.yml.jinja",
]
PRIVATE = "127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
_DEFAULT = re.compile(r"\$\{ADMIN_IP_ALLOWLIST:-([^}]*)\}")


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_the_admin_allowlist_defaults_to_private_ranges(name: str) -> None:
    defaults = _DEFAULT.findall((PROJECT / name).read_text())
    assert defaults, f"{name} sets no ADMIN_IP_ALLOWLIST default"
    assert set(defaults) == {PRIVATE}


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_no_default_admits_every_address(name: str) -> None:
    for default in _DEFAULT.findall((PROJECT / name).read_text()):
        assert not {"0.0.0.0/0", "::/0"} & set(default.split(","))
