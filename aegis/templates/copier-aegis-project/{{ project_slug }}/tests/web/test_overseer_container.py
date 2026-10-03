"""The Container section: every Overseer page with a container behind it
(Redis here) gets one; its table of instances from ``app.core.runtime`` arrives and
refreshes over SSE, so opening it never waits on Docker. A page with no container has none."""

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_container
from app.core import series
from app.services.system import ui_runtime
from app.services.system.models import ComponentStatus
from tests._fake_runtime import REDIS, FakeRuntime, use_runtime
from tests.web.dom import chart_json, checked, one, select, text
from tests.web.overseer import sign_in, status_with

CACHE = ComponentStatus(name="cache", message="Connected", metadata={})
AUTH = ComponentStatus(name="auth", message="Ready", metadata={})


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    sign_in(app, monkeypatch, status_with(CACHE, services=[AUTH]))
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    return TestClient(app)


def _html(client: TestClient, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200, response.text
    return response.text


def test_a_page_with_a_container_gets_the_section(client: TestClient) -> None:
    links = [
        text(a)
        for a in select(
            _html(client, "/overseer/components/cache"), "#overseer-subnav nav a"
        )
    ]
    assert links[-1] == "Container"


def test_the_section_opens_without_waiting_on_the_runtime(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page asks the runtime nothing: it renders from the sampler's last
    reading (pending before the first), and the stream keeps it fresh."""
    fake = use_runtime(monkeypatch, FakeRuntime(REDIS))
    html = _html(client, "/overseer/components/cache/container")
    assert (fake.listed, fake.asked) == (0, [])
    assert "Reading" in text(one(html, "#container [data-pending]"))
    assert (
        one(html, "#container").get("sse-connect")
        == "/overseer/events/container/redis?window=900"
    )


async def test_the_stream_sends_the_table_and_the_charts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    frames = [f async for f in overseer_container.events("redis", max_frames=1)]
    sent = {frame.split("\n", 1)[0]: frame for frame in frames}
    assert "app-redis-1" in sent["event: container"]
    assert "chart-container-cpu-data" in sent["event: container-cpu"]
    assert "chart-container-memory-data" in sent["event: container-memory"]


def test_the_charts_draw_what_was_sampled_without_asking_the_runtime(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """History is in the cache already, so the charts open full."""
    fake = use_runtime(monkeypatch, FakeRuntime(REDIS))
    asyncio.run(
        series.record(
            {f"{ui_runtime.SAMPLER}:redis:app-redis-1:{ui_runtime.CPU}": 12.5}
        )
    )
    html = _html(client, "/overseer/components/cache/container")
    data = chart_json(html, "chart-container-cpu-data")
    assert data["series"] == [{"label": "app-redis-1", "values": [12.5]}]
    assert (fake.listed, fake.asked) == (0, [])


async def test_without_a_deploy_target_it_says_what_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS, backend_name="none"))
    (frame,) = [f async for f in overseer_container.events("redis", max_frames=1)]
    assert "aegis add deploy" in frame  # and no charts of nothing


def test_the_range_chips_pick_the_window_and_the_stream_follows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    html = _html(client, "/overseer/components/cache/container?window=1800")
    assert checked(html, '#container input[name="window"]') == ["1800"]
    assert one(html, "#container").get("sse-connect") == (
        "/overseer/events/container/redis?window=1800"
    )
    assert "Last 30 minutes" in text(one(html, "#chart-container-cpu"))


async def test_the_stream_charts_the_window_it_was_opened_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    frames = [
        f async for f in overseer_container.events("redis", window=3600, max_frames=1)
    ]
    (cpu,) = [f for f in frames if f.startswith("event: container-cpu")]
    start, end = chart_json(cpu.split("data: ", 1)[1], "chart-container-cpu-data")[
        "window"
    ]
    assert end - start == 3600 * 1000


def test_a_page_with_no_container_has_no_section(client: TestClient) -> None:
    links = [
        text(a)
        for a in select(
            _html(client, "/overseer/services/auth"), "#overseer-subnav nav a"
        )
    ]
    assert "Container" not in links
