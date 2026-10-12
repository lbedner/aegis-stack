"""The browser component: what a connection asks the server for, and
whether the health check tells up from down. Where the server is from each
side lives with the other services in tests/test_host_port_resolution.py.

The last test drives a real browser through BROWSER_URL; it runs when the
browser server is up (`make serve`) and skips otherwise.
"""

import json
from typing import Any

import httpx
import pytest

from app.components.browser import client, health
from app.services.system.models import ComponentStatusType
from tests._browser import live_browser


async def test_connect_sends_the_launch_options(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class FakeBrowser:
        async def close(self) -> None:
            seen["closed"] = True

    class FakeChromium:
        async def connect(self, url: str, headers: dict[str, str]) -> FakeBrowser:
            seen["url"] = url
            seen["launch"] = json.loads(headers["x-playwright-launch-options"])
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        async def __aenter__(self) -> "FakePlaywright":
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(client, "async_playwright", FakePlaywright)
    monkeypatch.setattr(client, "browser_url", lambda: "ws://browser:3000/")

    async with client.connect(["--no-sandbox"]):
        pass

    assert seen == {
        "url": "ws://browser:3000/",
        "launch": {"headless": True, "args": ["--no-sandbox"]},
        "closed": True,
    }


def _serve(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    real = httpx.AsyncClient
    monkeypatch.setattr(
        health.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(health, "browser_url", lambda: "ws://browser:3000/")


async def test_health_is_healthy_when_the_server_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch, lambda request: httpx.Response(200, text="Running"))

    status = await health.check_browser_health()

    assert status.status == ComponentStatusType.HEALTHY
    assert status.metadata[health.BrowserFact.ENDPOINT] == "ws://browser:3000/"


async def test_health_is_unhealthy_when_the_server_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    _serve(monkeypatch, refuse)

    status = await health.check_browser_health()

    assert status.status == ComponentStatusType.UNHEALTHY


async def test_a_page_opened_through_the_server_reads_its_title() -> None:
    async with live_browser() as browser:
        page = await browser.new_page()
        await page.goto("data:text/html,<title>aegis browser</title>")
        assert await page.title() == "aegis browser"
