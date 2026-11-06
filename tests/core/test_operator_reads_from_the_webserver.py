"""The webserver calls its own operator endpoints over loopback.

``/health/detailed`` is ``require_operator``: open to loopback, closed to
anything else without the docs login. The CLI and ``live_status`` read it at
``API_BASE_URL``, which in a container defaults to ``webserver:PORT`` for the
workers' sake; from inside the webserver that name arrives from the Docker
network, not loopback, and was refused.
"""

import pytest

from tests.core._compose import load, render


@pytest.mark.parametrize("redis", [False, True])
def test_the_webserver_calls_itself_over_loopback(redis: bool) -> None:
    webserver = load(render("docker-compose.yml.jinja", include_redis=redis))[
        "services"
    ]["webserver"]
    assert "API_BASE_URL=http://localhost:${PORT:-8000}" in webserver["environment"]
