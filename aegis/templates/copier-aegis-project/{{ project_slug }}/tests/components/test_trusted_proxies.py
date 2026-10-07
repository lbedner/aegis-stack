"""Who the client is behind a proxy: ``X-Forwarded-For`` is believed only
from a trusted sender, so a caller reaching the app's port directly can't
name itself, and every consumer (rate limits, sessions, audit, traffic,
connections) reads the one rewritten address."""

from typing import Any

import pytest

from app.components.backend.security.trusted_proxies import TrustedProxyMiddleware
from app.core.config import settings
from app.entrypoints import webserver

PROXY = "172.18.0.5"  # where the bundled Traefik reaches the app from


@pytest.fixture(autouse=True)
def trusting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)


async def _client_seen(sender: str, forwarded: str, kind: str = "http") -> str | None:
    """The client address the app behind the middleware sees."""
    seen: dict[str, Any] = {}

    async def app(scope: dict[str, Any], _receive: Any, _send: Any) -> None:
        seen["client"] = scope["client"]

    scope = {
        "type": kind,
        "scheme": "http" if kind == "http" else "ws",
        "path": "/",
        "client": (sender, 5000),
        "headers": [(b"x-forwarded-for", forwarded.encode())],
    }
    await TrustedProxyMiddleware(app)(scope, None, None)
    return seen["client"][0]


async def test_the_proxy_names_the_client() -> None:
    assert await _client_seen(PROXY, "203.0.113.7") == "203.0.113.7"


async def test_a_caller_at_the_port_cannot_name_itself() -> None:
    """The hole a header rule alone left open: straight to a published
    port, a one-entry forged header is also the last entry."""
    assert await _client_seen("198.51.100.9", "203.0.113.7") == "198.51.100.9"


async def test_trusted_hops_are_walked_back_to_the_client() -> None:
    """A CDN in front of Traefik: each trusted hop is skipped, and what
    the caller wrote before the first one is never reached."""
    seen = await _client_seen(PROXY, "1.2.3.4, 203.0.113.7, 10.0.0.3")
    assert seen == "203.0.113.7"


async def test_a_websocket_is_rewritten_too() -> None:
    assert await _client_seen(PROXY, "203.0.113.7", "websocket") == "203.0.113.7"


async def test_off_believes_no_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
    assert await _client_seen(PROXY, "203.0.113.7") == PROXY


async def test_the_trusted_senders_are_a_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", ["192.0.2.1"])
    assert await _client_seen(PROXY, "203.0.113.7") == PROXY
    assert await _client_seen("192.0.2.1", "203.0.113.7") == "203.0.113.7"


def test_the_engine_never_rewrites_the_client_itself() -> None:
    """Uvicorn trusts loopback on its own and granian trusts nothing: the
    app's middleware decides for both, so they serve alike."""
    assert webserver.uvicorn_settings("asyncio")["proxy_headers"] is False
