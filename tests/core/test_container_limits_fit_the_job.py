"""The process a person waits on is never the most throttled one.

A compose ``cpus`` limit is a freeze, not a slowdown: the kernel stops the
process once its share of each 100ms period is spent. The webserver is the
only interactive process in a generated stack and a single event loop -
every page, every htmx fragment, the Overseer and every streamed token run
on it - so a ceiling it hits shows up as the whole app stalling at once.
Measured on a running stack at ``cpus: '0.5'``: throttled in 11.8% of
periods, 83 seconds frozen, while ``worker-system`` at 1.0 stalled 6 times.
"""

from __future__ import annotations

import re
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"
# Everything that runs in the background rather than for a waiting person.
BACKGROUND = ("scheduler", "worker-system", "worker-load-test")
DEFAULT = re.compile(r"\$\{[A-Z_]+:-([0-9.]+)\}")


def _compose(**overrides: Any) -> dict[str, Any]:
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    context = {
        **get_copier_defaults(),
        "project_slug": "demo",
        "include_worker": True,
        "include_scheduler": True,
        "include_redis": True,
        **overrides,
    }
    rendered = env.get_template(
        f"{PROJECT_SLUG_PLACEHOLDER}/docker-compose.yml.jinja"
    ).render(context)
    return yaml.safe_load(rendered)


def _cpus(service: dict[str, Any]) -> float:
    """The limit a stack gets when nothing overrides it."""
    raw = str(service["deploy"]["resources"]["limits"]["cpus"])
    match = DEFAULT.search(raw)
    return float(match.group(1) if match else raw)


def _check(compose: dict[str, Any]) -> None:
    services = compose["services"]
    webserver = _cpus(services["webserver"])
    for name in BACKGROUND:
        if name in services:
            assert _cpus(services[name]) <= webserver, (
                f"{name} may use more CPU than the webserver a person is "
                f"waiting on ({_cpus(services[name])} > {webserver})"
            )


def test_no_background_container_outranks_the_webserver() -> None:
    _check(_compose())


def test_nor_with_finance_sizing_the_system_worker_up() -> None:
    _check(_compose(include_finance=True, include_database=True))


def test_the_webserver_limit_can_be_raised_without_editing_compose() -> None:
    raw = str(
        _compose()["services"]["webserver"]["deploy"]["resources"]["limits"]["cpus"]
    )
    assert DEFAULT.search(raw), f"webserver cpus is hardcoded: {raw!r}"
