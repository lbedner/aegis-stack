"""Healthchecks run code that knows what healthy means.

The scheduler's healthcheck was an inline ``python -c`` string repeating the
heartbeat path and the 60s window from ``heartbeat.py``; it now runs that
module. The dev asset watcher inherited the image's ``curl /health`` check
while serving nothing, so it always read unhealthy (#1252).
"""

from __future__ import annotations

from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"


def _render(name: str, **overrides: Any) -> dict[str, Any]:
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    context = {**get_copier_defaults(), "project_slug": "demo", **overrides}
    return yaml.safe_load(
        env.get_template(f"{PROJECT_SLUG_PLACEHOLDER}/{name}").render(context)
    )


def test_the_scheduler_healthcheck_runs_the_heartbeat_module() -> None:
    compose = _render("docker-compose.yml.jinja", include_scheduler=True)
    test = compose["services"]["scheduler"]["healthcheck"]["test"]

    assert test == ["CMD", "python", "-m", "app.components.scheduler.heartbeat"]


def test_the_asset_watcher_does_not_inherit_the_http_healthcheck() -> None:
    compose = _render("docker-compose.dev.yml.jinja", include_htmx=True)
    watcher = compose["services"]["build-static-watcher"]

    assert watcher.get("healthcheck", {}).get("disable") is True
