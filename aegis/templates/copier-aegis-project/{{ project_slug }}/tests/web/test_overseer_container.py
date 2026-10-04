"""The Container section: every Overseer page with a container behind it
(Redis here) gets one; its table of instances from ``app.core.runtime`` arrives and
refreshes over SSE, so opening it never waits on Docker. A page with no container has none."""

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_container
from app.core import runtime, series
from app.core.config import settings
from app.core.runtime import Instance
from app.services.system import topology, ui_runtime
from app.services.system.models import ComponentStatus
from tests._fake_runtime import REDIS, WORKER, FakeRuntime, use_runtime
from tests.web.dom import chart_json, checked, none, one, select, text
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
    assert links[-2:] == ["Container", "Logs"]


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
    frames = [f async for f in overseer_container.events("redis", max_frames=1)]
    (table,) = [
        f for f in frames if f.startswith(f"event: {overseer_container.EVENT}\n")
    ]
    assert "aegis add deploy" in table
    assert not [
        f for f in frames if "chart" in f.split("\n", 1)[0]
    ]  # no charts of nothing


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


def test_each_container_restarts_after_a_confirm(client: TestClient) -> None:
    """A Restart on each row opens a confirm whose button posts to
    the restart API (which audits it); a container that is not
    this app's has no confirm to open."""
    asyncio.run(ui_runtime.containers("redis"))  # the sampler's first reading
    html = _html(client, "/overseer/components/cache/container")
    opener = one(html, f'#container [data-container="{REDIS.name}"] [hx-get]')
    assert text(opener) == "Restart"
    assert opener.get("hx-get") == overseer_container.RESTART.format(name=REDIS.name)
    dialog = _html(client, opener.get("hx-get"))
    button = one(dialog, "[hx-post]")
    assert button.get("hx-post") == f"/api/v1/runtime/containers/{REDIS.name}/restart"
    assert f"Restart {REDIS.name}?" in dialog
    assert (
        client.get(
            overseer_container.RESTART.format(name="someone-elses-db-1")
        ).status_code
        == 404
    )


def test_each_container_is_a_card_of_steady_figures(client: TestClient) -> None:
    """One card per instance: its name, state and restart in the header, and
    its live figures as a fixed strip, so a value changing width never moves
    the others (a table re-sized its columns on every frame)."""
    asyncio.run(ui_runtime.containers("redis"))
    html = _html(client, "/overseer/components/cache/container")
    none(html, "#container table")
    card = one(html, f'#container [data-container="{REDIS.name}"]')
    assert text(one(card, "[data-state]")) == "running"
    figures = {text(dt): text(dt.getnext()) for dt in select(card, "dl dt")}
    assert figures == {
        "CPU": "12.5%",
        "Memory": "128.0 MB",
        "Network": "2.0 KB in",
        "Disk I/O": "4.0 KB read",
    }
    captions = [text(c) for c in select(card, "dl dd + dd")]
    assert captions == ["of 512.0 MB · 25.0%", "1.0 KB out", "0 B write"]


def test_the_overview_opens_with_a_glance_at_its_containers(client: TestClient) -> None:
    """The Scheduler's and Cache's Overview answers "is it okay"
    before anything else: each container's state, uptime, CPU, and memory as
    a share of its limit, its Restart, and the way to its Container and Logs
    sections; kept live by its own stream."""
    asyncio.run(ui_runtime.containers("redis"))
    html = _html(client, "/overseer/components/cache")
    glance = one(html, "#runtime-glance")
    assert glance.get("sse-connect") == "/overseer/events/glance/redis"
    row = one(glance, f'[data-glance="{REDIS.name}"]')
    assert text(one(row, "[data-state]")) == "running"
    assert "12.5%" in text(row)
    assert text(one(row, "[data-memory]")).endswith("25.0%")
    links = {a.get("href") for a in select(row, "a")}
    assert links == {
        "/overseer/components/cache/container",
        "/overseer/components/cache/logs",
    }
    assert one(row, "button[hx-get]").get(
        "hx-get"
    ) == overseer_container.RESTART.format(name=REDIS.name)


async def test_the_stream_keeps_the_glance_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    frames = [f async for f in overseer_container.glance_events("redis", max_frames=1)]
    (sent,) = [f for f in frames if f.startswith("event: ")]
    assert sent.startswith(f"event: {overseer_container.GLANCE_EVENT}")
    assert REDIS.name in sent


def test_the_home_page_is_every_glance(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Overseer's Overview: everything in the sidebar as one list, in its
    order, a row each (one per container), the name first and linking to its
    page. A page with containers behind it shows their glance; anything else
    runs in the webserver, and says so beside its health check's line. Kept
    live by one stream for the whole stack."""
    server = Instance(
        id="s1", name="app-webserver-1", service="webserver", state="running"
    )
    use_runtime(monkeypatch, FakeRuntime(server, REDIS))
    asyncio.run(ui_runtime.containers("redis"))
    html = _html(client, "/overseer")
    stack = one(html, "#overview-stack")
    assert stack.get("sse-connect") == f"{overseer_container.OVERVIEW_EVENTS}?view=list"
    none(stack, "h2")  # a column, not a heading per entry
    cache = one(stack, '[data-overview="cache"]')
    assert cache.get("data-glance") == REDIS.name
    title = one(cache, "[data-title]")
    assert (text(title), title.get("href")) == ("Cache", "/overseer/components/cache")
    auth = one(stack, '[data-overview="auth"][data-health]')
    assert "in app-webserver-1" in text(auth) and "Ready" in text(auth)
    keys = [r.get("data-overview") for r in select(stack, "[data-overview]")]
    assert keys.index("cache") < keys.index("auth")  # components, then services


async def test_the_home_stream_sends_every_glance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.components.web_frontend import overseer_nav

    snapshot = status_with(CACHE, ComponentStatus(name="worker", message="Up"))
    monkeypatch.setattr(overseer_nav, "last_system_status", lambda: snapshot)
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER))
    frames = [f async for f in overseer_container.overview_events(max_frames=1)]
    (sent,) = [f for f in frames if f.startswith("event: ")]
    assert REDIS.name in sent and WORKER.name in sent


def test_the_home_page_also_reads_as_cards(client: TestClient) -> None:
    """A view toggle (List or Cards, kept in the address like every filter):
    a card a sidebar entry, its status and health line; with containers, its
    CPU and memory and their lines over the last 15 minutes; without, a few
    of its health check's own figures."""
    asyncio.run(ui_runtime.containers("redis"))
    html = _html(client, "/overseer?view=cards")
    assert checked(html, '#overview-view input[name="view"]') == ["cards"]
    stack = one(html, "#overview-stack")
    assert "view=cards" in stack.get("sse-connect")
    cache = one(stack, '[data-card="cache"]')
    assert len(select(cache, "svg polyline")) == 2  # CPU and memory
    assert "12.5%" in text(cache)
    auth = one(stack, '[data-card="auth"]')
    assert "Ready" in text(auth)
    none(html, "[data-overview]")  # not the list


def test_a_cards_figures_are_its_health_checks_own() -> None:
    """The figures the generic page shows (``NavItem.details``), the first
    few: never the ``type`` every check sets, nothing nested, nothing that
    names a place or a credential."""
    from app.components.web_frontend.overseer_nav import NavItem

    check = ComponentStatus(
        name="database",
        message="ok",
        metadata={
            "type": "component_check",
            "engine": "sqlite",
            "tables": 44,
            "size_bytes": 6_900_000,
            "url": "sqlite:///data/app.db",
            "api_key": "sk-123",
            "nested": {"a": 1},
            "pool_size": 5,
        },
    )
    entry = NavItem(
        group="components",
        name="database",
        title="Database",
        url="",
        status="",
        component=check,
    )
    assert overseer_container.facts(entry.details) == [
        ("Engine", "sqlite"),
        ("Tables", "44"),
        ("Size bytes", "6900000"),
    ]


def test_the_home_page_also_reads_as_a_map(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A third view: the stack's shape (``topology``), each process a node
    in its tier linking to its page, the connections between them drawn,
    and what runs inside the webserver as chips in the Server's node."""
    server = ComponentStatus(name="backend", message="FastAPI", metadata={})
    sign_in(app, monkeypatch, status_with(server, CACHE, services=[AUTH]))
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    asyncio.run(ui_runtime.containers("redis"))
    client = TestClient(app)
    html = _html(client, "/overseer?view=map")
    assert one(html, '[data-node="backend"] [data-chip="auth"]') is not None
    assert checked(html, '#overview-view input[name="view"]') == ["map"]
    stack = one(html, "#overview-stack")
    cache = one(stack, '[data-node="cache"]')
    assert one(cache, "[data-title]").get("href") == "/overseer/components/cache"
    assert "12.5%" in text(cache)
    paths = select(stack, "svg path[data-link]")
    shape = topology.shape(
        [n.get("data-node") for n in select(stack, "[data-node]")]
        + [c.get("data-chip") for c in select(stack, "[data-chip]")]
    )
    assert len(paths) == len(shape.links)
    assert one(stack, '[data-chip="auth"]').get("href") == "/overseer/services/auth"


@pytest.mark.parametrize(
    "path",
    [
        "/overseer/components/cache",
        "/overseer/components/cache/container",
        "/overseer?view=list",
        "/overseer?view=cards",
        "/overseer?view=map",
    ],
)
def test_a_stopped_container_draws_everywhere(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """A stopped container has no stats to read, and still draws as stopped."""
    stopped = Instance(id="r1", name=REDIS.name, service="redis", state="exited")
    use_runtime(monkeypatch, FakeRuntime(stopped))
    asyncio.run(ui_runtime.containers("redis"))
    assert "exited" in _html(client, path)


def test_a_figure_past_its_threshold_takes_its_tone(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live figure (not its label) in the warning's amber, on the
    Container card and the home page's card, sparkline included."""
    monkeypatch.setattr(settings, "MEMORY_THRESHOLD_PERCENT", 30.0)  # 25% warns
    asyncio.run(ui_runtime.containers("redis"))
    card = one(_html(client, "/overseer/components/cache/container"), "#container")
    figures = {text(dt): dt.getnext() for dt in select(card, "dl dt")}
    assert figures["Memory"].get("data-tone") == "warn"
    assert not figures["CPU"].get("data-tone")  # a fine figure stays plain
    home = one(_html(client, "/overseer?view=cards"), '[data-card="cache"]')
    assert one(home, "[data-spark=memory] svg").get("data-tone") == "warn"
    assert one(home, "[data-spark=cpu] svg").get("data-tone") == "ok"


def test_restarting_the_server_overseer_runs_on_says_the_page_drops(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests._fake_runtime import SERVER

    use_runtime(monkeypatch, FakeRuntime(SERVER, REDIS))
    monkeypatch.setattr(runtime.socket, "gethostname", lambda: SERVER.id)
    own = _html(client, overseer_container.RESTART.format(name=SERVER.name))
    assert "this page drops" in own
    assert "this page drops" not in _html(
        client, overseer_container.RESTART.format(name=REDIS.name)
    )
