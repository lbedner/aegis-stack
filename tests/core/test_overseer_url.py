"""Where a project's Overseer answers: the htmx one when the project has it,
the Flet dashboard otherwise, on the port ``make serve`` will take."""

import shutil
import socket
from pathlib import Path

import pytest

from aegis.core.component_files import PROJECT_SLUG_PLACEHOLDER, get_template_path
from aegis.core.components import COMPONENTS
from aegis.core.overseer_url import _webserver_port, local_overseer_url, overseer_path

RESOLVER = get_template_path() / PROJECT_SLUG_PLACEHOLDER / "scripts/resolve_ports.py"


def _project(tmp_path: Path, *, htmx: bool) -> Path:
    (tmp_path / "scripts").mkdir()
    shutil.copy(RESOLVER, tmp_path / "scripts/resolve_ports.py")
    if htmx:
        (tmp_path / COMPONENTS["htmx"].marker_path).mkdir(parents=True)
    return tmp_path


def test_a_project_with_htmx_opens_the_htmx_overseer(tmp_path: Path) -> None:
    assert overseer_path(_project(tmp_path, htmx=True)) == "/overseer"


def test_a_flet_only_project_opens_the_dashboard(tmp_path: Path) -> None:
    assert overseer_path(_project(tmp_path, htmx=False)) == "/dashboard/"


def test_the_local_url_skips_a_port_already_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """By the project's own rule (``resolve_ports``), from its base."""
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        monkeypatch.setenv("WEBSERVER_PORT_BASE", str(port))
        url = local_overseer_url(_project(tmp_path, htmx=True))
    assert url == f"http://localhost:{port + 1}/overseer"


def test_the_local_url_keeps_the_port_the_last_run_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stack already served beside another one keeps its port
    (``.env.ports``), so the link names the port ``make serve`` keeps."""
    monkeypatch.delenv("WEBSERVER_PORT_BASE", raising=False)
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
    project = _project(tmp_path, htmx=True)
    (project / ".env.ports").write_text(f"WEBSERVER_HOST_PORT={port}\n")
    _webserver_port.cache_clear()
    assert local_overseer_url(project) == f"http://localhost:{port}/overseer"


def test_a_project_from_before_the_shared_rule_still_gets_a_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An older project's resolver names no ``webserver_port``: its base,
    or the next free port after it, as that resolver finds one."""
    monkeypatch.setenv("WEBSERVER_PORT_BASE", "8123")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/resolve_ports.py").write_text(
        "def _find_free_port(start):\n    return start + 1\n"
    )
    _webserver_port.cache_clear()
    assert local_overseer_url(tmp_path) == "http://localhost:8124/dashboard/"
