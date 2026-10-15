"""The dev stack publishes its ports on localhost only. Without the auth
service, Overseer is anyone's to read on the dev build, a table's rows
included; a port on every interface would hand them to the whole network."""

import re

import pytest

from tests.core._compose import load, render

DEV = "docker-compose.dev.yml.jinja"
EVERYTHING = {
    "include_redis": True,
    "include_storage": True,
    "include_browser": True,
    "include_htmx": True,
    "database_engine": "postgres",
    "ollama_mode": "docker",
}


@pytest.mark.parametrize("ingress", [False, True])
def test_every_dev_port_binds_localhost(ingress: bool) -> None:
    services = load(render(DEV, **EVERYTHING, include_ingress=ingress))["services"]
    published = [
        (name, str(port))
        for name, service in services.items()
        for port in (service or {}).get("ports", [])
    ]
    assert published
    assert [p for p in published if not p[1].startswith("127.0.0.1:")] == []


def test_the_base_files_ports_are_the_ones_dev_replaces() -> None:
    """Compose adds the base file's ports to the dev file's; the base file
    publishes only the webserver's, which the dev file overrides."""
    base = load(render("docker-compose.yml.jinja", **EVERYTHING))["services"]
    assert [name for name, s in base.items() if (s or {}).get("ports")] == ["webserver"]
    text = render(DEV, **EVERYTHING)
    assert re.search(r"\n  webserver:\n(?:    .*\n)*?    ports: !override\n", text)


def test_the_docs_server_binds_localhost() -> None:
    assert "0.0.0.0" not in render("scripts/dev_tasks.py.jinja")
