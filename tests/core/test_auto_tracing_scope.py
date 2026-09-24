"""Each process traces the packages it actually runs.

``install_auto_tracing`` hardcoded ``app.components.frontend`` and every
process called it, so the scheduler and the worker - which never import the
UI - announced frontend tracing on every boot. Only the web process builds
the UI, so only it asks for the frontend package.
"""

from __future__ import annotations

import ast
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"
FRONTEND = "app.components.frontend"


def _render(path: str) -> str:
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    context: dict[str, Any] = {
        **get_copier_defaults(),
        "project_slug": "demo",
        "include_worker": True,
        "include_scheduler": True,
        "include_observability": True,
    }
    return env.get_template(f"{PROJECT_SLUG_PLACEHOLDER}/{path}").render(context)


def _traced_extras(path: str) -> list[str]:
    """The packages a module passes to ``install_auto_tracing``."""
    calls = [
        node
        for node in ast.walk(ast.parse(_render(path)))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "install_auto_tracing"
    ]
    assert len(calls) == 1, f"{path} should install auto-tracing exactly once"
    return [ast.literal_eval(arg) for arg in calls[0].args]


def test_the_web_process_traces_the_ui_it_builds() -> None:
    assert FRONTEND in _traced_extras("app/integrations/main.py.jinja")


@pytest.mark.parametrize(
    "entrypoint",
    ["app/entrypoints/scheduler.py.jinja", "app/entrypoints/worker.py.jinja"],
)
def test_background_processes_do_not_trace_the_ui(entrypoint: str) -> None:
    assert FRONTEND not in _traced_extras(entrypoint)


def test_services_are_traced_without_being_asked_for() -> None:
    """The shared list is what every process gets; it must not carry the UI."""
    source = _render("app/components/backend/middleware/logfire_tracing.py.jinja")
    tree = ast.parse(source)
    shared = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", None) == "SERVICE_MODULES" for t in node.targets)
    )
    modules = ast.literal_eval(shared)
    assert "app.services" in modules
    assert FRONTEND not in modules
