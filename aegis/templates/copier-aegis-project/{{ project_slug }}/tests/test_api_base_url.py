"""Every CLI that calls this app's own API needs its address.

``make serve`` shifts the published host port when 8000 is taken, while
the container keeps listening on ``PORT``. A CLI command runs on the
host, so it needs the published one. Before this, ``API_BASE_URL`` did
not exist at all and every caller fell back to a hardcoded
``localhost:8000``: the port moved and the clients did not follow.
"""

from app.core.config import Settings


def test_it_follows_the_configured_port() -> None:
    assert Settings(PORT=9123).API_BASE_URL == "http://localhost:9123"


def test_the_published_port_wins_over_the_container_port() -> None:
    """``make serve`` publishes 8001 while the container serves 8000."""
    settings = Settings(PORT=8000, WEBSERVER_HOST_PORT=8001)
    assert settings.API_BASE_URL == "http://localhost:8001"


def test_an_explicit_value_wins() -> None:
    """A container or a tunnel names its own address."""
    settings = Settings(
        PORT=9123, WEBSERVER_HOST_PORT=8001, API_BASE_URL="https://api.example.test"
    )
    assert settings.API_BASE_URL == "https://api.example.test"
