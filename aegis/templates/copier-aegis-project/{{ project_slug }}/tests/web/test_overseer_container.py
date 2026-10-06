"""The Container section: every Overseer page with a container behind it
(Redis here) gets one; its table of instances from ``app.core.runtime`` arrives and
refreshes over SSE, so opening it never waits on Docker. A page with no container has none."""

import asyncio
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_container, overseer_map
from app.core import runtime, series
from app.core.config import settings
from app.core.runtime import Instance
from app.services.system import topology, ui_runtime
from app.services.system.models import (
    ComponentStatus,
    ComponentStatusType,
    LoadCosts,
)
from tests._fake_runtime import (
    REDIS,
    WORKER,
    FakeRuntime,
    use_load_costs,
    use_runtime,
)
from tests.web.dom import chart_json, checked, none, one, select, text
from tests.web.overseer import page_html, sign_in, status_with

CACHE = ComponentStatus(name="cache", message="Connected", metadata={})
AUTH = ComponentStatus(name="auth", message="Ready", metadata={})


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    sign_in(app, monkeypatch, status_with(CACHE, services=[AUTH]))
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    return TestClient(app)


def test_a_page_with_a_container_gets_the_section(client: TestClient) -> None:
    links = [
        text(a)
        for a in select(
            page_html(client, "/overseer/components/cache"), "#overseer-subnav nav a"
        )
    ]
    assert links[-2:] == ["Container", "Logs"]


def test_the_section_opens_without_waiting_on_the_runtime(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page asks the runtime nothing: it renders from the sampler's last
    reading (pending before the first), and the stream keeps it fresh."""
    fake = use_runtime(monkeypatch, FakeRuntime(REDIS))
    html = page_html(client, "/overseer/components/cache/container")
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
    html = page_html(client, "/overseer/components/cache/container")
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
    html = page_html(client, "/overseer/components/cache/container?window=1800")
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


async def test_after_its_first_frame_a_chart_sends_only_its_new_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The page's chart holds what it was sent, so a tick carries a few
    points, not the whole window again; a new line sends it all."""
    readings = iter([["a"], ["a"], ["a", "b"]])

    async def section(page: str, window: int, wait: bool = True) -> tuple:
        names = next(readings)
        data = series.chart(
            {name: [(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)] for name in names}, str
        )
        return {"rows": []}, [{"key": "cpu", "data": data}]

    monkeypatch.setattr(ui_runtime, "section", section)
    monkeypatch.setattr(overseer_container, "render", lambda view: "")
    monkeypatch.setattr(series, "TICK_SECONDS", 0)
    sent = [
        chart_json(f.split("data: ", 1)[1], "chart-container-cpu-data")
        async for f in overseer_container.events("redis", max_frames=3)
        if f.startswith("event: container-cpu")
    ]
    first, tick, new_line = sent
    assert first["labels"] == [1000, 2000, 3000]
    assert tick["labels"] == [3000] and tick["points"] == 3
    assert new_line["labels"] == [1000, 2000, 3000]


def test_a_page_with_no_container_has_no_section(client: TestClient) -> None:
    links = [
        text(a)
        for a in select(
            page_html(client, "/overseer/services/auth"), "#overseer-subnav nav a"
        )
    ]
    assert "Container" not in links


def test_each_container_restarts_after_a_confirm(client: TestClient) -> None:
    """A Restart on each row opens a confirm whose button posts to
    the restart API (which audits it); a container that is not
    this app's has no confirm to open."""
    asyncio.run(ui_runtime.containers("redis"))  # the sampler's first reading
    html = page_html(client, "/overseer/components/cache/container")
    opener = one(html, f'#container [data-container="{REDIS.name}"] [hx-get]')
    assert text(opener) == "Restart"
    assert opener.get("hx-get") == overseer_container.RESTART.format(name=REDIS.name)
    dialog = page_html(client, opener.get("hx-get"))
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
    html = page_html(client, "/overseer/components/cache/container")
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
    html = page_html(client, "/overseer/components/cache")
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
    html = page_html(client, "/overseer")
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
    html = page_html(client, "/overseer?view=cards")
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
    html = page_html(client, "/overseer?view=map")
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


def _failing(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """The Database down and the Server failing with it; the Cache fine."""
    down = ComponentStatusType.UNHEALTHY
    sign_in(
        app,
        monkeypatch,
        status_with(
            ComponentStatus(name="backend", status=down, message="No database"),
            ComponentStatus(name="database", status=down, message="Refused"),
            CACHE,
            services=[AUTH],
        ),
    )
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    return TestClient(app)


def test_a_line_takes_the_tone_of_what_it_leads_to(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A call fails when what it calls does: the line into the Database is
    red, the failing Server's line into the healthy Cache is not."""
    html = page_html(_failing(app, monkeypatch), "/overseer?view=map")
    tones = {
        (p.get("data-from"), p.get("data-to")): p.get("data-tone")
        for p in select(html, "svg path[data-link]")
    }
    assert tones[("backend", "database")] == "error"
    assert tones[("backend", "cache")] == "ok"


@pytest.mark.parametrize(
    ("view", "entry"),
    [("map", "data-node"), ("list", "data-overview"), ("cards", "data-card")],
)
def test_a_part_failing_with_what_it_depends_on_names_it(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, view: str, entry: str
) -> None:
    html = page_html(_failing(app, monkeypatch), f"/overseer?view={view}")
    assert text(one(html, f'[{entry}="backend"] [data-cause]')) == (
        "Likely cause: Database"
    )
    none(html, f'[{entry}="database"] [data-cause]')


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
    assert "exited" in page_html(client, path)


def test_a_figure_past_its_threshold_takes_its_tone(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live figure (not its label) in the warning's amber, on the
    Container card and the home page's card, sparkline included."""
    monkeypatch.setattr(settings, "MEMORY_THRESHOLD_PERCENT", 30.0)  # 25% warns
    asyncio.run(ui_runtime.containers("redis"))
    card = one(page_html(client, "/overseer/components/cache/container"), "#container")
    figures = {text(dt): dt.getnext() for dt in select(card, "dl dt")}
    assert figures["Memory"].get("data-tone") == "warn"
    assert not figures["CPU"].get("data-tone")  # a fine figure stays plain
    home = one(page_html(client, "/overseer?view=cards"), '[data-card="cache"]')
    assert one(home, "[data-spark=memory] svg").get("data-tone") == "warn"
    assert one(home, "[data-spark=cpu] svg").get("data-tone") == "ok"


def test_restarting_the_server_overseer_runs_on_says_the_page_drops(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests._fake_runtime import SERVER

    use_runtime(monkeypatch, FakeRuntime(SERVER, REDIS))
    monkeypatch.setattr(runtime.socket, "gethostname", lambda: SERVER.id)
    own = page_html(client, overseer_container.RESTART.format(name=SERVER.name))
    assert "this page drops" in own
    assert "this page drops" not in page_html(
        client, overseer_container.RESTART.format(name=REDIS.name)
    )


def test_a_runtime_that_does_not_answer_is_a_503_not_a_crash(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any route that reaches the runtime: the app maps its errors once (an
    unknown container 404, no answer 503), so none of them is a 500."""
    use_runtime(monkeypatch, FakeRuntime(REDIS, fail=True))
    response = client.get(overseer_container.RESTART.format(name=REDIS.name))
    assert response.status_code == 503


@pytest.mark.parametrize(
    ("view", "entry", "healthy"),
    [
        ("map", "data-node", "cache"),
        ("list", "data-overview", "auth"),  # its containers' rows show the Cache
        ("cards", "data-card", "cache"),
    ],
)
def test_healthy_is_only_its_dot_and_anything_else_says_what_it_is(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, view: str, entry: str, healthy: str
) -> None:
    html = page_html(_failing(app, monkeypatch), f"/overseer?view={view}")
    one(html, f'[{entry}="{healthy}"] [data-healthy]')
    none(html, f'[{entry}="database"] [data-healthy]')
    assert "unhealthy" in text(one(html, f'[{entry}="database"]'))


def test_a_healthy_pages_heading_is_only_its_dot(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A component with no page of its own gets the generic one: its
    heading, its current status and its checks say healthy by the dot
    alone, anything else in words."""
    probe = ComponentStatus(
        name="probe", status=ComponentStatusType.WARNING, message="Slow"
    )
    plain = ComponentStatus(
        name="observability",
        message="Exporting",
        metadata={},
        sub_components={"probe": probe},
    )
    sign_in(app, monkeypatch, status_with(plain))
    html = page_html(TestClient(app), "/overseer/components/observability")
    one(html, "header [data-healthy]")
    one(html, "#card-current-status [data-healthy]")
    warning = one(html, "#card-checks [data-tone]")
    assert (text(warning), warning.get("data-tone")) == ("warning", "warn")


@pytest.mark.parametrize(
    ("view", "entry"), [("map", "data-node"), ("cards", "data-card")]
)
def test_an_entry_in_trouble_is_outlined_in_its_tone(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, view: str, entry: str
) -> None:
    html = page_html(_failing(app, monkeypatch), f"/overseer?view={view}")
    database = one(html, f'[{entry}="database"]')
    assert database.get("data-tone") == "error"
    assert "tone-border" in database.get("class").split()


def test_cards_put_trouble_first_and_can_show_only_it(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Client side, so a live frame keeps the choice: the stack carries it
    (CSS orders and hides the cards by their tone), trouble first at the
    start."""
    html = page_html(_failing(app, monkeypatch), "/overseer?view=cards")
    stack = one(html, "#overview-stack")
    assert (stack.get("data-order"), stack.get("data-only")) == ("trouble", "false")
    one(html, "[data-toggle=trouble-first]")
    one(html, "[data-toggle=only-trouble]")
    none(page_html(_failing(app, monkeypatch), "/overseer?view=map"), "[data-toggle]")


def _entry(key: str) -> dict[str, Any]:
    return {"key": key, "title": key, "tone": "ok"}


@pytest.mark.parametrize(
    ("installed", "width"),
    [
        (["ingress", "backend", "database", "cache", "storage", "ollama"], 20.0),
        (["backend", "database"], overseer_map.MAX_NODE_WIDTH),
    ],
)
def test_the_map_sizes_its_nodes_to_the_stack(
    installed: list[str], width: float
) -> None:
    """The busiest tier shares the map's width: four data stores get a fifth
    of it each; a small stack's nodes stop at a node's size. Each tier
    spreads across the whole width."""
    found = overseer_map.layout([_entry(key) for key in installed])
    assert found["map_node_width"] == pytest.approx(width)
    bottom = max(n["top"] for n in found["map_nodes"])
    data = [n["left"] for n in found["map_nodes"] if n["top"] == bottom]
    gap = 100 / len(data)  # each node centred in an equal share of the width
    assert data == pytest.approx([gap * (i + 0.5) for i in range(len(data))])


def test_the_views_switch_by_icon_and_still_say_which(client: TestClient) -> None:
    """Each view is an icon, named for a reader and on hover; every icon
    it points at is drawn on the page."""
    html = page_html(client, "/overseer")
    chips = select(html, "#overview-view label")
    assert [c.get("title") for c in chips] == ["List", "Cards", "Map"]
    assert [text(one(c, ".sr-only:not(input)")) for c in chips] == [
        "List",
        "Cards",
        "Map",
    ]
    used = {one(c, "svg use").get("href") for c in chips}
    defined = {f"#{s.get('id')}" for s in select(html, "svg[data-icons] symbol")}
    assert len(used) == 3 and used <= defined


def test_the_servers_services_sit_two_to_a_row() -> None:
    """Room for each name in full, and its cost to load."""
    stack = [_entry(key) for key in ("backend", "auth", "ai", "blog")]
    found = overseer_map.layout(stack)
    server = next(n for n in found["map_nodes"] if n["key"] == "backend")
    two_rows = overseer_map.NODE_HEIGHT + 2 * overseer_map.CHIP_ROW
    assert server["height"] == two_rows


def test_a_service_chip_says_what_it_costs_to_load(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = ComponentStatus(name="backend", message="FastAPI", metadata={})
    sign_in(app, monkeypatch, status_with(server, services=[AUTH]))
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    use_load_costs(monkeypatch, LoadCosts(core=1, parts={"service_auth": 50 * 2**20}))
    html = page_html(TestClient(app), "/overseer?view=map")
    chip = one(html, '[data-chip="auth"]')
    assert text(one(chip, "[data-load]")) == "50.0 MB"
