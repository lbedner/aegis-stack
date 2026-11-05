"""Overseer > Resources (``overseer_resources``), kept live over SSE."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.components.web_frontend import overseer_resources
from app.core.config import settings
from app.core.formatting import format_bytes
from app.core.runtime import Instance
from app.services.system import ui_resources
from app.services.system.models import LoadCosts
from tests._fake_runtime import (
    REDIS,
    STATS,
    STOPPED,
    UNHEALTHY,
    WORKER,
    FakeRuntime,
    use_host_checks,
    use_load_costs,
    use_runtime,
)
from tests.web.dom import chart_json, checked, none, one, select, text
from tests.web.overseer import page_html, sign_in, status_with

PAGE = "/overseer/resources"


def _client(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, *instances: Instance
) -> TestClient:
    sign_in(app, monkeypatch, status_with())
    use_runtime(monkeypatch, FakeRuntime(*instances))
    use_host_checks(monkeypatch)
    # The page opens on the containers sampler's last reading: take one.
    asyncio.run(ui_resources.overview())
    return TestClient(app)


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    return _client(app, monkeypatch, REDIS, WORKER, STOPPED)


def test_the_sidebar_leads_to_it(client: TestClient) -> None:
    link = one(page_html(client, "/overseer"), f'#overseer-nav a[href="{PAGE}"]')
    assert text(link) == "Resources"


def test_it_takes_the_whole_canvas(client: TestClient) -> None:
    assert one(page_html(client, PAGE), "[data-width]").get("data-width") == "workspace"


def test_each_resource_says_this_stack_and_free_over_its_chart(
    client: TestClient,
) -> None:
    """The split rides its chart's header, live: the bands already draw this
    stack, the host's in use line the rest."""
    html = page_html(client, PAGE)
    for key in ("cpu", "memory"):
        live = one(html, f"#chart-resources-{key} header [sse-swap]")
        assert live.get("sse-swap") == f"{overseer_resources.SPLIT_EVENT}-{key}"
        parts = {p.get("data-part") for p in select(live, "[data-part]")}
        assert parts == {"stack", "free"}
    stack = one(html, '#chart-resources-memory [data-part="stack"]')
    assert format_bytes(2 * STATS.memory_used) in text(stack)


def test_only_a_container_not_well_is_listed(client: TestClient) -> None:
    """The charts draw every running container; one stopped draws nothing,
    so it is named, with the way to its part's page."""
    html = page_html(client, PAGE)
    stopped = one(html, f"#container-{STOPPED.name}")
    assert one(stopped, "a").get("href", "").startswith("/overseer/")
    # Its container, without the project's name before it.
    assert text(one(stopped, "[data-container]")) == "worker-media-1"
    none(html, f"#container-{REDIS.name}")
    none(html, f"#container-{WORKER.name}")


def test_a_container_past_its_memory_alert_is_listed(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """By the rule that raises its part's dot (``container_health``): a
    dot with no row under it would leave the warning unexplained."""
    monkeypatch.setattr(settings, "MEMORY_THRESHOLD_PERCENT", 20.0)
    html = page_html(_client(app, monkeypatch, REDIS), PAGE)
    assert "Memory" in text(one(html, f"#container-{REDIS.name}"))


def test_nothing_is_listed_while_every_container_runs(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = page_html(_client(app, monkeypatch, REDIS, WORKER), PAGE)
    none(html, "#resources-containers")


async def test_the_stream_sends_the_page_again(monkeypatch: pytest.MonkeyPatch) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS, STOPPED))
    use_host_checks(monkeypatch)
    frames = [f async for f in overseer_resources.events(max_frames=1)]
    assert frames[0].startswith(f"event: {overseer_resources.EVENT}")
    assert STOPPED.name in frames[0]


def test_an_unhealthy_container_says_so_in_amber(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running while Docker's healthcheck on it fails: it says so, not its
    phase, in amber, as its part's status does (``container_health``)."""
    html = page_html(_client(app, monkeypatch, REDIS, UNHEALTHY), PAGE)
    badge = one(html, f"#container-{UNHEALTHY.name} span.toned")
    assert (text(badge), badge.get("data-tone")) == ("unhealthy", "warn")
    none(html, f"#container-{REDIS.name}")


def test_it_charts_every_figure_over_the_chosen_window(client: TestClient) -> None:
    html = page_html(client, f"{PAGE}?window=3600")
    for key in ("cpu", "memory", "network", "disk"):
        one(html, f'canvas[data-chart-data="chart-resources-{key}-data"]')
    assert checked(html, '#resources input[name="window"]') == ["3600"]
    assert "window=3600" in one(html, "#resources").get("sse-connect")


async def test_the_stream_sends_each_split_apart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In its chart's header, so a frame of its own."""
    use_runtime(monkeypatch, FakeRuntime(REDIS, STOPPED))
    use_host_checks(monkeypatch)
    frames = [f async for f in overseer_resources.events(max_frames=1)]
    sent = {frame.split("\n", 1)[0]: frame for frame in frames}
    split = sent[f"event: {overseer_resources.SPLIT_EVENT}-memory"]
    body = sent[f"event: {overseer_resources.EVENT}"]
    assert 'data-part="free"' in split and "sse-swap" not in split
    assert 'data-part="free"' not in body and STOPPED.name in body


async def test_the_stream_sends_each_chart(monkeypatch: pytest.MonkeyPatch) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    use_host_checks(monkeypatch)
    frames = [f async for f in overseer_resources.events(max_frames=1)]
    sent = {frame.split("\n", 1)[0] for frame in frames}
    assert {
        f"event: {overseer_resources.EVENT}-{key}" for key in ("cpu", "memory")
    } <= sent


@pytest.mark.parametrize("measured", [True, False])
def test_it_shows_what_each_service_costs_to_load(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, measured: bool
) -> None:
    """Inside the webserver, where Docker sees one container: each service's
    cost to load, a bar a service laid flat so the names read, or that it
    is being measured."""

    use_load_costs(
        monkeypatch, LoadCosts(core=1, parts={"backend": 2}) if measured else None
    )
    html = page_html(client, PAGE)
    card = one(html, "#chart-resources-load")
    data = chart_json(card, "chart-resources-load-data")
    measuring = one(card, "[data-chart-empty]")
    if measured:
        assert (data["labels"], data["series"][0]["values"]) == (["Server"], [2])
        assert (data["format"], data["horizontal"]) == ("bytes", True)
    assert ("hidden" in measuring.get("class", "")) is measured


async def test_the_stream_leaves_the_load_costs_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Measured once a day: re-sent every tick, its chart would draw again."""
    use_runtime(monkeypatch, FakeRuntime(REDIS, STOPPED))
    use_host_checks(monkeypatch)
    use_load_costs(monkeypatch, LoadCosts(core=1, parts={"backend": 2}))
    frames = [f async for f in overseer_resources.events(max_frames=1)]
    assert not [f for f in frames if "resources-load" in f]
