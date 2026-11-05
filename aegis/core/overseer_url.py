"""Where a project answers locally: its Overseer (the htmx one when the
project has the htmx frontend, the Flet dashboard otherwise) and its other
pages, on the port ``make serve`` will publish."""

import os
import runpy
from functools import cache
from pathlib import Path

from .components import COMPONENTS


def overseer_path(project_path: Path) -> str:
    if (project_path / COMPONENTS["htmx"].marker_path).exists():
        return "/overseer"
    return "/dashboard/"


@cache
def _webserver_port(project_path: Path) -> int:
    """The project's own rule (``scripts/resolve_ports.py``, which
    ``make serve`` runs): the port its last run kept, the base, or the next
    free port after it; the base itself for a project without one. An
    older project's resolver has no ``webserver_port``, only its free-port
    search. Asked once a run, so every line that prints it names the same
    port."""
    base = int(os.environ.get("WEBSERVER_PORT_BASE", "8000"))
    resolver = project_path / "scripts/resolve_ports.py"
    if not resolver.exists():
        return base
    found = runpy.run_path(str(resolver))
    if "webserver_port" in found:
        return found["webserver_port"]()
    return found["_find_free_port"](base)


def local_url(project_path: Path, path: str) -> str:
    return f"http://localhost:{_webserver_port(project_path)}{path}"


def local_overseer_url(project_path: Path) -> str:
    return local_url(project_path, overseer_path(project_path))
