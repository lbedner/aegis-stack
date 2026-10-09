"""The Logs section: every Overseer page with a container behind it (Redis
here) gets one, after Container. It shows the window's lines from each
container (``ui_logs``), newest last, filters them by window, level and
text, and follows new ones over SSE while it is open."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_code, overseer_logs
from app.core.config import settings
from app.services.system.patterns import PROJECT_ROOT
from app.core.runtime import LogLine, parse_log_line
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_title
from tests._fake_runtime import (
    REDIS,
    STOPPED,
    WORKER,
    FakeRuntime,
    container_lookups,
    use_runtime,
)
from tests.web.dom import checked, none, one, select, text
from tests.web.overseer import CACHE, page_html, sign_in, status_with

PAGE = "/overseer/components/cache/logs"
AI_TITLE = get_component_title("service_ai")


def _at(second: int, text: str) -> LogLine:
    return parse_log_line(f"2026-10-03T20:45:{second:02d}.000000000Z {text}", "stdout")


# The error line's traceback: Python's own frame, one in the app's own code,
# then a library's.
TRACE = [
    "Traceback (most recent call last):",
    '  File "<frozen runpy>", line 88, in _run_code',
    f'  File "{PROJECT_ROOT}/app/core/log.py", line 36, in put',
    '  File "/opt/venv/lib/python3.14/site-packages/redis/client.py", line 5, in send',
    "OSError: disk full",
]
LINES = {
    REDIS.name: [
        _at(1, json.dumps({"level": "info", "event": "Ready to accept connections"})),
        _at(2, json.dumps({"level": "error", "event": "Write failed", "key": "jobs"})),
        *(_at(3, line) for line in TRACE),
    ]
}


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    sign_in(app, monkeypatch, status_with(CACHE))
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=LINES))
    return TestClient(app)


def _messages(html: str) -> list[str]:
    """The lines a Logs page shows, by their message, in order."""
    return [text(one(row, "[data-message]")) for row in select(html, "#logs-lines tr")]


def test_the_section_follows_container(client: TestClient) -> None:
    links = [
        text(a)
        for a in select(
            page_html(client, "/overseer/components/cache"), "#overseer-subnav nav a"
        )
    ]
    assert links[-2:] == ["Container", "Logs"]


def test_the_lines_read_newest_first_with_level_fields_and_traceback(
    client: TestClient,
) -> None:
    html = page_html(client, PAGE)
    rows = select(html, "#logs-lines tr")
    assert [text(one(row, "[data-message]")) for row in rows] == [
        "Write failed",
        "Ready to accept connections",
    ]
    failed = rows[0]
    assert "error" in text(one(failed, "[data-level]"))
    assert "key=jobs" in text(failed)
    # Shown, highlighted, the moment its row opens: not a row, not folded.
    trace = one(failed, "[data-log-trace]")
    assert "OSError: disk full" in text(trace)
    assert text(one(trace, ".highlight .gr")) == "OSError"
    none(failed, "details")
    # The app's own frame links to its line in Overseer > Code; a library's
    # does not.
    url = overseer_code.line_url("app/core/log.py", 36)
    own, frame = select(trace, "a")
    assert frame.get("href") == url
    assert "log.py" in text(frame)
    # The innermost frame in the app's own code, named beside "Traceback",
    # and the library's frames dimmed in the trace.
    assert own.get("href") == url and text(own) == "app/core/log.py:36"
    dimmed = [text(f) for f in select(trace, ".library-frame")]
    assert ["frozen runpy" in dimmed[0], "redis/client.py" in dimmed[1]] == [True, True]
    # New lines join at the top, where the newest already is.
    assert one(html, "#logs-lines").get("hx-swap") == "afterbegin"


def test_oldest_first_on_request(client: TestClient) -> None:
    html = page_html(client, f"{PAGE}?order=asc")
    rows = select(html, "#logs-lines tr")
    assert text(one(rows[0], "[data-message]")) == "Ready to accept connections"
    assert one(html, "#logs-lines").get("hx-swap") == "beforeend"
    assert (
        one(html, '#logs select[name="order"] option[selected]').get("value") == "asc"
    )
    assert "order=asc" in one(html, "#logs").get("sse-connect")


def test_every_cell_copies_what_it_shows(client: TestClient) -> None:
    failed = select(page_html(client, PAGE), "#logs-lines tr")[0]
    assert [button.get("data-copy") for button in select(failed, "[data-copy]")] == [
        "20:45:02",
        REDIS.name,
        "Write failed",
        "\n".join(TRACE),
    ]


def test_a_line_is_three_cells_with_its_level_as_a_tag(client: TestClient) -> None:
    """Time, source and the line: the level sits in the line, and only when
    it has one."""
    failed, ready = select(page_html(client, PAGE), "#logs-lines tr")
    assert len(select(failed, "td")) == 3
    assert text(one(failed, "td:last-child [data-level]")) == "error"
    assert len(select(ready, "td")) == 3
    none(ready, "[data-level]")  # info is the normal case: no tag


def test_buttons_scroll_to_either_end(client: TestClient) -> None:
    targets = [
        b.get("data-scroll-to")
        for b in select(page_html(client, PAGE), "#logs [data-scroll-to]")
    ]
    assert targets == ["#logs-lines > tr:first-child", "#logs-lines > tr:last-child"]


def test_the_filters_narrow_the_lines_and_keep_their_state(client: TestClient) -> None:
    html = page_html(client, f"{PAGE}?level=error&window=3600&q=write")
    assert _messages(html) == ["Write failed"]
    assert one(html, '#logs input[name="q"]').get("value") == "write"
    assert checked(html, '#logs input[name="window"]') == ["3600"]
    assert [
        i.get("value") for i in select(html, '#logs input[name="level"][checked]')
    ] == ["error"]
    assert one(html, "#logs").get("sse-connect") == (
        "/overseer/events/logs/redis?level=error&order=desc"
    )


async def test_the_stream_appends_new_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    followed = {REDIS.name: [_at(4, json.dumps({"level": "info", "event": "Saved"}))]}
    use_runtime(monkeypatch, FakeRuntime(REDIS, followed=followed))
    frames = [f async for f in overseer_logs.events("redis", {})]
    sent = [f for f in frames if f.startswith(f"event: {overseer_logs.EVENT}")]
    assert len(sent) == 1 and "Saved" in sent[0]


def test_without_a_deploy_target_it_says_so_and_follows_nothing(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign_in(app, monkeypatch, status_with(CACHE))
    use_runtime(monkeypatch, FakeRuntime(REDIS, backend_name="none"))
    html = page_html(TestClient(app), PAGE)
    assert "aegis add deploy" in text(one(html, "#logs"))
    none(html, "[sse-connect]#logs, #logs [sse-connect]")


def test_an_unknown_page_has_no_stream(client: TestClient) -> None:
    assert client.get("/overseer/events/logs/nowhere").status_code == 404


# Overseer > Logs: every page's lines in one view.
ALL = "/overseer/logs"
EVERY = {
    REDIS.name: LINES[REDIS.name],
    WORKER.name: [_at(5, json.dumps({"level": "info", "event": "Task done"}))],
}


@pytest.fixture
def everything(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    sign_in(app, monkeypatch, status_with(CACHE))
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER, lines=EVERY))
    return TestClient(app)


def test_the_sidebar_leads_to_every_services_logs(everything: TestClient) -> None:
    link = one(
        page_html(everything, "/overseer"), '#overseer-nav a[href="/overseer/logs"]'
    )
    assert text(link) == "Logs"


def test_every_services_lines_merge_with_a_link_to_their_page(
    everything: TestClient,
) -> None:
    rows = select(page_html(everything, ALL), "#logs-lines tr")
    assert [text(one(row, "[data-message]")) for row in rows] == [
        "Task done",
        "Write failed",
        "Ready to accept connections",
    ]
    service = one(rows[0], "[data-service] a")
    assert (text(service), service.get("href")) == (
        "Worker",
        "/overseer/components/worker",
    )
    assert one(rows[1], "[data-service] a").get("href") == "/overseer/components/cache"


def test_the_service_filter_narrows_the_lines_and_the_stream(
    everything: TestClient,
) -> None:
    html = page_html(everything, f"{ALL}?service=worker")
    assert _messages(html) == ["Task done"]
    assert [
        i.get("value") for i in select(html, '#logs input[name="service"][checked]')
    ] == ["worker"]
    assert one(html, "#logs").get("sse-connect") == (
        "/overseer/events/logs?order=desc&service=worker"
    )


def test_following_can_be_paused(everything: TestClient) -> None:
    """Paused, a new line is dropped rather than added (the SSE extension's
    cancellable ``htmx:sseBeforeMessage``)."""
    html = page_html(everything, ALL)
    assert "preventDefault" in one(html, "#logs").get("x-on:htmx:sse-before-message")
    one(html, "#logs [data-pause]")


async def test_the_whole_stream_names_each_lines_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    followed = {WORKER.name: [_at(6, json.dumps({"level": "info", "event": "Again"}))]}
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER, followed=followed))
    frames = [f async for f in overseer_logs.everything_events({})]
    sent = [f for f in frames if f.startswith(f"event: {overseer_logs.EVENT}")]
    assert (
        len(sent) == 1
        and "Again" in sent[0]
        and "/overseer/components/worker" in sent[0]
    )


def test_a_row_carries_its_levels_tone_for_the_stripe(client: TestClient) -> None:
    failed, ready = select(page_html(client, PAGE), "#logs-lines tr")
    assert (failed.get("data-tone"), ready.get("data-tone")) == ("error", None)


def test_the_lead_the_columns_repeat_is_left_out_but_copied(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign_in(app, monkeypatch, status_with(CACHE))
    lines = {REDIS.name: [_at(7, "2026-10-03 20:45:07 [info ] Started")]}
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=lines))
    (row,) = select(page_html(TestClient(app), PAGE), "#logs-lines tr")
    none(row, "[data-prefix]")
    assert text(one(row, "[data-message]")) == "Started"
    copies = [b.get("data-copy") for b in select(row, "[data-copy]")]
    assert "2026-10-03 20:45:07 [info ] Started" in copies


def test_the_search_filters_the_lines_on_the_page_without_a_request(
    client: TestClient,
) -> None:
    """Typing narrows and marks what is already loaded (app.js
    ``data-filter``); the server sends every line, and changing another
    filter keeps the text (it rides in the URL, not in a request)."""
    html = page_html(client, f"{PAGE}?q=write")
    search = one(html, "#logs input[data-filter]")
    assert (search.get("data-filter"), search.get("value")) == ("#logs-lines", "write")
    assert len(select(html, "#logs-lines tr")) == 2  # not filtered on the server
    assert "data-filter" in one(html, "#logs form").get("hx-trigger")


def test_a_field_reads_as_a_muted_key_and_its_value(client: TestClient) -> None:
    failed = select(page_html(client, PAGE), "#logs-lines tr")[0]
    (key,) = select(failed, "[data-field-key]")
    assert (text(key), text(key.getnext())) == ("key=", "jobs")


def test_each_service_has_its_own_color(everything: TestClient) -> None:
    from app.services.system import ui_logs

    rows = select(page_html(everything, ALL), "#logs-lines tr")
    dot = one(rows[0], "[data-service] [data-dot]")
    assert f"--aegis-chart-{ui_logs.color_of('worker') + 1}" in dot.get("style")


def test_every_icon_points_at_a_symbol_the_page_has(client: TestClient) -> None:
    """The copy icons draw from the one icon sprite, which every page
    carries (``base.html``), not only the chat."""
    html = page_html(client, PAGE)
    used = {u.get("href") for u in select(html, "#logs-lines svg use")}
    defined = {f"#{s.get('id')}" for s in select(html, "svg[data-icons] symbol")}
    assert used and used <= defined


@pytest.mark.parametrize(
    ("path", "width"),
    [
        ("/overseer/logs", "workspace"),
        ("/overseer/deployments", "workspace"),
        ("/overseer?view=map", "workspace"),
        ("/overseer", "document"),
        ("/overseer/settings", "document"),
    ],
)
def test_operational_pages_take_the_whole_canvas(
    client: TestClient, path: str, width: str
) -> None:
    """A workspace (the data is the page: Logs, Deployments, the Map) runs
    to the gutters; a document (Overview, Settings) keeps its column."""
    assert one(page_html(client, path), "[data-width]").get("data-width") == width


def test_the_log_list_fills_the_screen(client: TestClient) -> None:
    """The list runs to the bottom of the window and scrolls inside it, so
    the filters above stay put."""
    scroller = one(page_html(client, "/overseer/logs"), "#logs [data-scroll]")
    assert "100vh" in scroller.get("class")


@pytest.fixture
def workers(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    sign_in(app, monkeypatch, status_with(CACHE))
    lines = {WORKER.name: [_at(1, "a")], STOPPED.name: [_at(2, "b")]}
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER, STOPPED, lines=lines))
    return TestClient(app)


def test_a_service_with_several_containers_names_which(workers: TestClient) -> None:
    """One source column: the service, then which of its containers only
    when it has more than one; the container's full name on hover."""
    rows = select(page_html(workers, ALL), "#logs-lines tr")
    sources = {text(one(r, "[data-message]")): one(r, "[data-service]") for r in rows}
    assert text(sources["a"]) == "Worker · system"
    assert sources["a"].get("title") == WORKER.name


def test_one_container_needs_no_name(everything: TestClient) -> None:
    rows = select(page_html(everything, ALL), "#logs-lines tr")
    cache = next(r for r in rows if text(one(r, "[data-message]")) == "Write failed")
    assert text(one(cache, "[data-service]")) == "Cache"


def test_a_line_shows_on_one_line_until_it_is_opened(client: TestClient) -> None:
    """Truncated to one line; a click opens a line, and Wrap opens them all."""
    html = page_html(client, PAGE)
    assert "data-open" in one(html, "#logs-lines").get("x-on:click")
    assert "wrap" in one(html, "#logs [data-wrap]").get("x-on:click")


def test_the_volume_shows_the_window_and_a_bar_narrows_to_its_time(
    client: TestClient,
) -> None:
    from app.services.system import ui_logs

    html = page_html(client, f"{PAGE}?window=0&level=error")
    bars = select(html, "#logs-volume a")
    assert len(bars) == ui_logs.VOLUME_BARS
    hot = [b for b in bars if select(b, '[data-tone="error"]')]
    assert len(hot) == 1
    href = hot[0].get("href")
    assert "from=" in href and "to=" in href and "level=error" in href
    narrowed = page_html(client, href)
    assert _messages(narrowed) == ["Write failed"]
    one(narrowed, "#logs-volume [aria-current]")
    one(narrowed, "#logs [data-clear-range]")


@pytest.mark.parametrize("window", ["0", "900", "86400"])
def test_the_volume_says_when_it_runs_from(client: TestClient, window: str) -> None:
    """How long ago the window starts, then now; a day back reads as its
    date, not the same clock time as now."""
    html = page_html(client, f"{PAGE}?window={window}")
    start, end = (text(s) for s in select(html, "#logs-volume-scale span"))
    assert start and start != end and end == "now"
    assert "lines" in select(html, "#logs-volume a")[0].get("title")


def test_a_range_marks_every_bar_it_covers(client: TestClient) -> None:
    """A drag's range (several bars) shows all of them picked."""
    bars = select(page_html(client, f"{PAGE}?window=0"), "#logs-volume a")
    narrowed = page_html(
        client,
        f"{PAGE}?window=0&from={bars[3].get('data-from')}&to={bars[5].get('data-to')}",
    )
    assert len(select(narrowed, "#logs-volume a[aria-current]")) == 3


def test_the_volume_can_be_dragged_across(client: TestClient) -> None:
    """Each bar carries where it ends, for a drag over several (app.js)."""
    html = page_html(client, f"{PAGE}?window=0")
    one(html, "#logs-volume[data-range]")
    bar = select(html, "#logs-volume a")[0]
    assert bar.get("data-to") and bar.get("draggable") == "false"


def test_the_volume_follows_the_lines_it_counts(client: TestClient) -> None:
    """Each line carries its time, and the strip names the list it marks
    the visible part of (app.js)."""
    html = page_html(client, f"{PAGE}?window=0")
    assert one(html, "#logs-volume").get("data-range-of") == "logs-lines"
    assert all(r.get("data-at", "").isdigit() for r in select(html, "#logs-lines tr"))


def test_a_worker_can_be_picked_by_its_container(workers: TestClient) -> None:
    """Under a service with several containers, each one, to read alone."""
    html = page_html(workers, ALL)
    picks = select(html, '#logs-services input[name="container"]')
    assert sorted(i.get("value") for i in picks) == sorted([WORKER.name, STOPPED.name])
    narrowed = page_html(workers, f"{ALL}?container={WORKER.name}")
    assert _messages(narrowed) == ["a"]
    assert f"container={WORKER.name}" in one(narrowed, "#logs").get("sse-connect")
    assert (
        one(narrowed, f'#logs-services input[value="{WORKER.name}"]').get("checked")
        is not None
    )


def test_the_service_picker_closes_on_a_click_anywhere_and_picks_all(
    everything: TestClient,
) -> None:
    picker = one(page_html(everything, ALL), "#logs-services")
    assert "open" in picker.get("@click.outside")
    one(picker, "[data-check-all]")


def test_a_pages_own_logs_pick_among_its_containers(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Worker page's Logs: a container picker, as Overseer > Logs has,
    only where the page has more than one."""
    worker = ComponentStatus(name="worker", message="Up")
    sign_in(app, monkeypatch, status_with(CACHE, worker))
    lines = {WORKER.name: [_at(1, "a")], STOPPED.name: [_at(2, "b")]}
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER, STOPPED, lines=lines))
    client = TestClient(app)
    page = "/overseer/components/worker/logs"
    picks = select(page_html(client, page), '#logs-containers input[name="container"]')
    assert sorted(i.get("value") for i in picks) == sorted([WORKER.name, STOPPED.name])
    narrowed = page_html(client, f"{page}?container={STOPPED.name}")
    rows = select(narrowed, "#logs-lines tr")
    assert [text(one(r, "[data-message]")) for r in rows] == ["b"]
    assert f"container={STOPPED.name}" in one(narrowed, "#logs").get("sse-connect")
    none(page_html(client, PAGE), "#logs-containers")  # the cache has one


def test_a_picked_range_narrows_the_stream_too(client: TestClient) -> None:
    """A line written after a picked bar's range is not added to it."""
    bars = select(page_html(client, f"{PAGE}?window=0"), "#logs-volume a")
    narrowed = page_html(client, bars[0].get("href"))
    stream = one(narrowed, "#logs").get("sse-connect")
    assert f"from={bars[0].get('data-from')}" in stream
    assert f"to={bars[0].get('data-to')}" in stream


@pytest.mark.parametrize("path", [ALL, PAGE])
def test_a_load_looks_its_containers_up_once(
    everything: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """The pickers and the lines read the same containers: one lookup."""
    seen = container_lookups(monkeypatch)
    page_html(everything, path)
    assert len(seen) == 1


async def test_a_stream_looks_its_containers_up_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER))
    seen = container_lookups(monkeypatch)
    [f async for f in overseer_logs.everything_events({})]
    assert len(seen) == 1


def test_application_service_picker_and_runtime_label(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    ai = ComponentStatus(name="ai", message="Up")
    auth = ComponentStatus(name="auth", message="Up")
    sign_in(app, monkeypatch, status_with(CACHE, services=(ai, auth)))
    lines = {
        WORKER.name: [
            _at(
                1,
                json.dumps({"level": "info", "event": "AI ready", "app_service": "ai"}),
            ),
            _at(
                2,
                json.dumps(
                    {"level": "info", "event": "Auth ready", "app_service": "auth"}
                ),
            ),
            _at(3, "old unattributed log"),
        ]
    }
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER, lines=lines))
    client = TestClient(app)
    html = page_html(client, ALL + "?app_service=ai")
    assert _messages(html) == ["AI ready"]
    assert checked(html, '#logs-services input[name="app_service"]') == ["ai"]
    assert {
        i.get("value") for i in select(html, '#logs-services input[name="app_service"]')
    } >= {"ai", "auth"}
    assert "app_service=ai" in one(html, "#logs").get("sse-connect")
    source = one(html, "#logs-lines [data-service]")
    # The service's title as this stack names it (a gated one is title-cased).
    assert AI_TITLE in text(source) and "Worker" in text(source)
    assert "old unattributed log" in _messages(page_html(client, ALL))


async def test_application_service_filter_reaches_live_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    followed = {
        WORKER.name: [
            _at(
                1,
                json.dumps({"level": "info", "event": "AI live", "app_service": "ai"}),
            ),
            _at(
                2,
                json.dumps(
                    {"level": "info", "event": "Auth live", "app_service": "auth"}
                ),
            ),
        ]
    }
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER, followed=followed))
    frames = [
        frame async for frame in overseer_logs.everything_events({"app_service": "ai"})
    ]
    html = "".join(frames)
    assert "AI live" in html and "Auth live" not in html
    assert "Worker" in html


@pytest.mark.parametrize("structured", [False, True])
def test_attributed_logs_put_dot_first_and_keep_metadata_in_expanded_row(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    structured: bool,
) -> None:
    ai = ComponentStatus(name="ai", message="Up")
    sign_in(app, monkeypatch, status_with(CACHE, services=(ai,)))
    fields = {
        "app_service": "ai",
        "emitting_service": "ai",
        "pathname": "/code/app/services/ai/usage.py",
    }
    raw = (
        json.dumps({"level": "info", "event": "Usage recorded", "cost": 0, **fields})
        if structured
        else "2026-10-03 20:45:01 [info ] Usage recorded [app.core.log] app_service=ai cost=0 emitting_service=ai pathname=/code/app/services/ai/usage.py"
    )
    use_runtime(monkeypatch, FakeRuntime(WORKER, lines={WORKER.name: [_at(1, raw)]}))
    row = one(page_html(TestClient(app), ALL), "#logs-lines tr")
    source = one(row, "[data-service]")
    assert source[0].get("data-dot") is not None
    assert text(one(source, "[data-app-service]")) == AI_TITLE
    assert "text-aegis-muted" in one(source, "a").get("class")
    message = text(one(row, ".log-line"))
    assert "Usage recorded" in message and "cost" in message
    assert all(key not in message for key in fields)
    details = one(row, "[data-log-metadata]")
    assert "log-trace" in details.get("class")
    assert all(f"{key}={value}" in text(details) for key, value in fields.items())


def test_a_frame_links_only_while_code_is_on(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "prod")
    none(one(page_html(client, PAGE), "[data-log-trace]"), "a")
