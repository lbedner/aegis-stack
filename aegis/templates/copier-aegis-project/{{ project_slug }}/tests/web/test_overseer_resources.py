"""Overseer > Resources (``overseer_resources``), kept live over SSE."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.components.web_frontend import overseer_resources
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
from tests.web.dom import checked, one, select, text
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


def test_each_resource_splits_into_this_stack_the_rest_and_free(
    client: TestClient,
) -> None:
    html = page_html(client, PAGE)
    for key in ("cpu", "memory"):
        parts = {
            p.get("data-part")
            for p in select(html, f'[data-split="{key}"] [data-part]')
        }
        assert parts == {"stack", "rest", "free"}
    stack = one(html, '[data-split="memory"] [data-part="stack"]')
    assert format_bytes(2 * STATS.memory_used) in text(stack)


def test_every_container_is_listed_with_a_way_to_its_page(client: TestClient) -> None:
    rows = select(page_html(client, PAGE), "#resources-containers tbody tr")
    names = [r.get("id").removeprefix("container-") for r in rows]
    assert names[-1] == STOPPED.name
    assert set(names) == {REDIS.name, WORKER.name, STOPPED.name}
    redis = rows[names.index(REDIS.name)]
    assert one(redis, "a").get("href") == "/overseer/components/cache"


async def test_the_stream_sends_the_page_again(monkeypatch: pytest.MonkeyPatch) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    use_host_checks(monkeypatch)
    frames = [f async for f in overseer_resources.events(max_frames=1)]
    assert frames[0].startswith(f"event: {overseer_resources.EVENT}")
    assert REDIS.name in frames[0]


def test_an_unhealthy_container_says_so_in_amber(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running while Docker's healthcheck on it fails: it says so, not its
    phase, in amber, as its part's status does (``container_health``)."""
    html = page_html(_client(app, monkeypatch, REDIS, UNHEALTHY), PAGE)
    rows = {
        r.get("id"): one(r, "span[data-tone]")
        for r in select(html, "#resources-containers tbody tr")
    }
    badge = rows[f"container-{UNHEALTHY.name}"]
    assert (text(badge), badge.get("data-tone")) == ("unhealthy", "warn")
    assert text(rows[f"container-{REDIS.name}"]) == "running"


def test_it_charts_every_figure_over_the_chosen_window(client: TestClient) -> None:
    html = page_html(client, f"{PAGE}?window=3600")
    for key in ("cpu", "memory", "network", "disk"):
        one(html, f'canvas[data-chart-data="chart-resources-{key}-data"]')
    assert checked(html, '#resources input[name="window"]') == ["3600"]
    assert "window=3600" in one(html, "#resources").get("sse-connect")


def test_the_charts_sit_right_under_the_stacks_totals(client: TestClient) -> None:
    html = page_html(client, PAGE)
    order = [
        html.index(marker)
        for marker in (
            'data-split="cpu"',
            'data-chart-data="chart-resources-cpu',
            'id="resources-containers"',
        )
    ]
    assert order == sorted(order)


async def test_the_stream_sends_the_totals_apart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Above the charts, so a frame of their own."""
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    use_host_checks(monkeypatch)
    frames = [f async for f in overseer_resources.events(max_frames=1)]
    sent = {frame.split("\n", 1)[0]: frame for frame in frames}
    totals = sent[f"event: {overseer_resources.TOTALS_EVENT}"]
    body = sent[f"event: {overseer_resources.EVENT}"]
    assert 'data-split="memory"' in totals
    assert "data-split" not in body and REDIS.name in body


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
    cost to load, in columns (a part a row would run the page long), or
    that it is being measured."""

    use_load_costs(
        monkeypatch, LoadCosts(core=1, parts={"backend": 2}) if measured else None
    )
    card = one(page_html(client, PAGE), "#card-inside-the-webserver")
    if measured:
        assert "Server" in text(one(card, "ol[data-columns] li"))
    else:
        one(card, "[data-measuring]")
