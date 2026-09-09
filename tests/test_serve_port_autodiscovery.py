"""Tests for `make serve` / `uv run poe serve` host-port auto-discovery.

Generated projects ship ``scripts/resolve_ports.py`` so ``serve`` /
``serve-bg`` pick a free host port when the default is already taken
(another ``serve`` running, an unrelated service on 8000, etc.) instead of
dying with ``bind: address already in use``. The module is a plain Python
file in the template tree (no Jinja), so it is loaded and exercised directly
here for fast framework-level feedback; the generated project's own
``tests/test_resolve_ports.py`` covers it end-to-end after rendering.
"""

from __future__ import annotations

import importlib.util
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

RESOLVE_PORTS_PY = (
    Path(__file__).parent.parent
    / "aegis"
    / "templates"
    / "copier-aegis-project"
    / "{{ project_slug }}"
    / "scripts"
    / "resolve_ports.py"
)


def _load_resolve_ports() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "template_resolve_ports", RESOLVE_PORTS_PY
    )
    assert spec and spec.loader, f"cannot load {RESOLVE_PORTS_PY}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def occupy_port() -> Iterator[int]:
    """Bind and listen on an ephemeral port for the duration of the block."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    try:
        yield sock.getsockname()[1]
    finally:
        sock.close()


def _free_port() -> int:
    """Return a currently-free ephemeral port (closed before returning)."""
    with occupy_port() as port:
        return port


def test_module_exists() -> None:
    assert RESOLVE_PORTS_PY.exists(), f"missing {RESOLVE_PORTS_PY}"


def test_find_free_port_returns_free_port_at_or_above_start() -> None:
    module = _load_resolve_ports()
    start = _free_port()
    chosen = module._find_free_port(start)
    assert chosen >= start


def test_find_free_port_skips_taken_port() -> None:
    module = _load_resolve_ports()
    with occupy_port() as taken:
        chosen = module._find_free_port(taken)
    assert chosen > taken


def test_resolve_ports_writes_only_allowlisted_keys(tmp_path: Path) -> None:
    module = _load_resolve_ports()
    ports_file = tmp_path / ".env.ports"
    ports = module.resolve_ports(
        ingress=True,
        postgres=True,
        redis=True,
        ollama=True,
        ports_file=ports_file,
    )
    content = ports_file.read_text()
    # Every key config.py declares as a Settings field may be persisted.
    # WEBSERVER_HOST_PORT is one of them: host-side CLI commands call
    # this app's own API, so they need the port compose published rather
    # than the one the container listens on.
    for key in (
        "WEBSERVER_HOST_PORT",
        "POSTGRES_HOST_PORT",
        "REDIS_HOST_PORT",
        "OLLAMA_HOST_PORT",
        "INGRESS_DASHBOARD_PORT",
    ):
        assert key in content
    # This one reaches docker compose via the returned dict, never
    # .env.ports — config.py has no field for it and its strict Settings
    # would reject the unknown key at boot.
    assert "INGRESS_HTTP_PORT" not in content
    assert ports["WEBSERVER_HOST_PORT"]
    assert ports["INGRESS_HTTP_PORT"]


def test_resolve_ports_backing_services_off_by_default(tmp_path: Path) -> None:
    module = _load_resolve_ports()
    ports = module.resolve_ports(
        ingress=False,
        postgres=False,
        redis=False,
        ollama=False,
        ports_file=tmp_path / ".env.ports",
    )
    assert set(ports) == {"WEBSERVER_HOST_PORT"}
