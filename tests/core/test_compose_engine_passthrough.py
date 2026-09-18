"""`make serve ENGINE=granian` has to reach the webserver container.

Compose does not join lists across a YAML merge key: a service that
declares its own ``environment`` replaces the ``x-app`` anchor's entirely.
The webserver declares one as soon as redis, storage or observability is
in the stack, so the passthrough has to be stated in both places or the
flag silently does nothing on exactly the stacks people run.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

COMPOSE = "docker-compose.yml.jinja"
PASSTHROUGH = "WEBSERVER_ENGINE=${WEBSERVER_ENGINE:-uvicorn}"


def _render(overrides: dict[str, Any]) -> dict[str, Any]:
    template_root = get_template_path() / "{{ project_slug }}"
    env = Environment(
        loader=FileSystemLoader(str(template_root)),
        keep_trailing_newline=True,
    )
    context = {**get_copier_defaults(), **overrides}
    rendered = env.get_template(COMPOSE).render(**context)
    return yaml.safe_load(rendered)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({}, id="base"),
        pytest.param({"include_redis": True}, id="redis"),
        pytest.param({"include_storage": True}, id="storage"),
        pytest.param({"include_observability": True}, id="observability"),
    ],
)
def test_the_webserver_sees_the_engine_setting(overrides: dict[str, Any]) -> None:
    compose = _render(overrides)
    webserver = compose["services"]["webserver"]

    # Whether it arrives through the anchor or the service's own list, the
    # container must end up with the variable.
    assert PASSTHROUGH in webserver["environment"]
