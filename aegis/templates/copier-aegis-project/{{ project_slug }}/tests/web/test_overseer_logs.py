"""The Logs section: every Overseer page with a container behind it (Redis
here) gets one, after Container. It shows the window's lines from each
container (``ui_logs``), newest last, filters them by window, level and
text, and follows new ones over SSE while it is open."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_logs
from app.core.runtime import LogLine, parse_log_line
from app.services.system.models import ComponentStatus
from tests._fake_runtime import REDIS, STOPPED, WORKER, FakeRuntime, use_runtime
from tests.web.dom import checked, none, one, select, text
from tests.web.overseer import sign_in, status_with

CACHE = ComponentStatus(name="cache", message="Connected", metadata={})
PAGE = "/overseer/components/cache/logs"


def _at(second: int, text: str) -> LogLine:
    return parse_log_line(f"2026-10-03T20:45:{second:02d}.000000000Z {text}", "stdout")


LINES = {
    REDIS.name: [
        _at(1, json.dumps({"level": "info", "event": "Ready to accept connections"})),
        _at(2, json.dumps({"level": "error", "event": "Write failed", "key": "jobs"})),
        _at(3, "Traceback (most recent call last):"),
        _at(3, "OSError: disk full"),
    ]
}


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    sign_in(app, monkeypatch, status_with(CACHE))
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=LINES))
    return TestClient(app)


def _html(client: TestClient, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200, response.text
    return response.text


def _messages(html: str) -> list[str]:
    """The lines a Logs page shows, by their message, in order."""
    return [text(one(row, "[data-message]")) for row in select(html, "#logs-lines tr")]


def test_the_section_follows_container(client: TestClient) -> None:
    links = [
        text(a)
        for a in select(
            _html(client, "/overseer/components/cache"), "#overseer-subnav nav a"
        )
    ]
    assert links[-2:] == ["Container", "Logs"]


def test_the_lines_read_newest_first_with_level_fields_and_traceback(
    client: TestClient,
) -> None:
    html = _html(client, PAGE)
    rows = select(html, "#logs-lines tr")
    assert [text(one(row, "[data-message]")) for row in rows] == [
        "Write failed",
        "Ready to accept connections",
    ]
    failed = rows[0]
    assert "error" in text(one(failed, "[data-level]"))
    assert "key=jobs" in text(failed)
    assert "OSError: disk full" in text(one(failed, "details"))  # folded, not a row
    # New lines join at the top, where the newest already is.
    assert one(html, "#logs-lines").get("hx-swap") == "afterbegin"


def test_oldest_first_on_request(client: TestClient) -> None:
    html = _html(client, f"{PAGE}?order=asc")
    rows = select(html, "#logs-lines tr")
    assert text(one(rows[0], "[data-message]")) == "Ready to accept connections"
    assert one(html, "#logs-lines").get("hx-swap") == "beforeend"
    assert (
        one(html, '#logs select[name="order"] option[selected]').get("value") == "asc"
    )
    assert "order=asc" in one(html, "#logs").get("sse-connect")


def test_every_cell_copies_what_it_shows(client: TestClient) -> None:
    failed = select(_html(client, PAGE), "#logs-lines tr")[0]
    assert [button.get("data-copy") for button in select(failed, "[data-copy]")] == [
        "20:45:02",
        REDIS.name,
        "Write failed",
        "Traceback (most recent call last):\nOSError: disk full",
    ]


def test_a_line_is_three_cells_with_its_level_as_a_tag(client: TestClient) -> None:
    """Time, source and the line: the level sits in the line, and only when
    it has one."""
    failed, ready = select(_html(client, PAGE), "#logs-lines tr")
    assert len(select(failed, "td")) == 3
    assert text(one(failed, "td:last-child [data-level]")) == "error"
    assert len(select(ready, "td")) == 3
    none(ready, "[data-level]")  # info is the normal case: no tag


def test_buttons_scroll_to_either_end(client: TestClient) -> None:
    targets = [
        b.get("data-scroll-to")
        for b in select(_html(client, PAGE), "#logs [data-scroll-to]")
    ]
    assert targets == ["#logs-lines > tr:first-child", "#logs-lines > tr:last-child"]


def test_the_filters_narrow_the_lines_and_keep_their_state(client: TestClient) -> None:
    html = _html(client, f"{PAGE}?level=error&window=3600&q=write")
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
    html = _html(TestClient(app), PAGE)
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
    link = one(_html(everything, "/overseer"), '#overseer-nav a[href="/overseer/logs"]')
    assert text(link) == "Logs"


def test_every_services_lines_merge_with_a_link_to_their_page(
    everything: TestClient,
) -> None:
    rows = select(_html(everything, ALL), "#logs-lines tr")
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
    html = _html(everything, f"{ALL}?service=worker")
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
    html = _html(everything, ALL)
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
    failed, ready = select(_html(client, PAGE), "#logs-lines tr")
    assert (failed.get("data-tone"), ready.get("data-tone")) == ("error", None)


def test_the_lead_the_columns_repeat_is_left_out_but_copied(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign_in(app, monkeypatch, status_with(CACHE))
    lines = {REDIS.name: [_at(7, "2026-10-03 20:45:07 [info ] Started")]}
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=lines))
    (row,) = select(_html(TestClient(app), PAGE), "#logs-lines tr")
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
    html = _html(client, f"{PAGE}?q=write")
    search = one(html, "#logs input[data-filter]")
    assert (search.get("data-filter"), search.get("value")) == ("#logs-lines", "write")
    assert len(select(html, "#logs-lines tr")) == 2  # not filtered on the server
    assert "data-filter" in one(html, "#logs form").get("hx-trigger")


def test_a_field_reads_as_a_muted_key_and_its_value(client: TestClient) -> None:
    failed = select(_html(client, PAGE), "#logs-lines tr")[0]
    (key,) = select(failed, "[data-field-key]")
    assert (text(key), text(key.getnext())) == ("key=", "jobs")


def test_each_service_has_its_own_color(everything: TestClient) -> None:
    from app.services.system import ui_logs

    rows = select(_html(everything, ALL), "#logs-lines tr")
    dot = one(rows[0], "[data-service] [data-dot]")
    assert f"--aegis-chart-{ui_logs.color_of('worker') + 1}" in dot.get("style")


def test_every_icon_points_at_a_symbol_the_page_has(client: TestClient) -> None:
    """The copy icons draw from the one icon sprite, which every page
    carries (``base.html``), not only the chat."""
    html = _html(client, PAGE)
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
    assert one(_html(client, path), "[data-width]").get("data-width") == width


def test_the_log_list_fills_the_screen(client: TestClient) -> None:
    """The list runs to the bottom of the window and scrolls inside it, so
    the filters above stay put."""
    scroller = one(_html(client, "/overseer/logs"), "#logs [data-scroll]")
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
    rows = select(_html(workers, ALL), "#logs-lines tr")
    sources = {text(one(r, "[data-message]")): one(r, "[data-service]") for r in rows}
    assert text(sources["a"]) == "Worker · system"
    assert sources["a"].get("title") == WORKER.name


def test_one_container_needs_no_name(everything: TestClient) -> None:
    rows = select(_html(everything, ALL), "#logs-lines tr")
    cache = next(r for r in rows if text(one(r, "[data-message]")) == "Write failed")
    assert text(one(cache, "[data-service]")) == "Cache"


def test_a_line_shows_on_one_line_until_it_is_opened(client: TestClient) -> None:
    """Truncated to one line; a click opens a line, and Wrap opens them all."""
    html = _html(client, PAGE)
    assert "data-open" in one(html, "#logs-lines").get("x-on:click")
    assert "wrap" in one(html, "#logs [data-wrap]").get("x-on:click")


def test_the_volume_shows_the_window_and_a_bar_narrows_to_its_time(
    client: TestClient,
) -> None:
    from app.services.system import ui_logs

    html = _html(client, f"{PAGE}?window=0&level=error")
    bars = select(html, "#logs-volume a")
    assert len(bars) == ui_logs.VOLUME_BARS
    hot = [b for b in bars if select(b, '[data-tone="error"]')]
    assert len(hot) == 1
    href = hot[0].get("href")
    assert "from=" in href and "to=" in href and "level=error" in href
    narrowed = _html(client, href)
    assert _messages(narrowed) == ["Write failed"]
    one(narrowed, "#logs-volume [aria-current]")
    one(narrowed, "#logs [data-clear-range]")


@pytest.mark.parametrize("window", ["0", "900", "86400"])
def test_the_volume_says_when_it_runs_from(client: TestClient, window: str) -> None:
    """How long ago the window starts, then now; a day back reads as its
    date, not the same clock time as now."""
    html = _html(client, f"{PAGE}?window={window}")
    start, end = (text(s) for s in select(html, "#logs-volume-scale span"))
    assert start and start != end and end == "now"
    assert "lines" in select(html, "#logs-volume a")[0].get("title")


def test_a_range_marks_every_bar_it_covers(client: TestClient) -> None:
    """A drag's range (several bars) shows all of them picked."""
    bars = select(_html(client, f"{PAGE}?window=0"), "#logs-volume a")
    narrowed = _html(
        client,
        f"{PAGE}?window=0&from={bars[3].get('data-from')}&to={bars[5].get('data-to')}",
    )
    assert len(select(narrowed, "#logs-volume a[aria-current]")) == 3


def test_the_volume_can_be_dragged_across(client: TestClient) -> None:
    """Each bar carries where it ends, for a drag over several (app.js)."""
    html = _html(client, f"{PAGE}?window=0")
    one(html, "#logs-volume[data-range]")
    bar = select(html, "#logs-volume a")[0]
    assert bar.get("data-to") and bar.get("draggable") == "false"


def test_the_volume_follows_the_lines_it_counts(client: TestClient) -> None:
    """Each line carries its time, and the strip names the list it marks
    the visible part of (app.js)."""
    html = _html(client, f"{PAGE}?window=0")
    assert one(html, "#logs-volume").get("data-range-of") == "logs-lines"
    assert all(r.get("data-at", "").isdigit() for r in select(html, "#logs-lines tr"))


def test_a_worker_can_be_picked_by_its_container(workers: TestClient) -> None:
    """Under a service with several containers, each one, to read alone."""
    html = _html(workers, ALL)
    picks = select(html, '#logs-services input[name="container"]')
    assert sorted(i.get("value") for i in picks) == sorted([WORKER.name, STOPPED.name])
    narrowed = _html(workers, f"{ALL}?container={WORKER.name}")
    assert _messages(narrowed) == ["a"]
    assert f"container={WORKER.name}" in one(narrowed, "#logs").get("sse-connect")
    assert (
        one(narrowed, f'#logs-services input[value="{WORKER.name}"]').get("checked")
        is not None
    )


def test_the_service_picker_closes_on_a_click_anywhere_and_picks_all(
    everything: TestClient,
) -> None:
    picker = one(_html(everything, ALL), "#logs-services")
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
    picks = select(_html(client, page), '#logs-containers input[name="container"]')
    assert sorted(i.get("value") for i in picks) == sorted([WORKER.name, STOPPED.name])
    narrowed = _html(client, f"{page}?container={STOPPED.name}")
    rows = select(narrowed, "#logs-lines tr")
    assert [text(one(r, "[data-message]")) for r in rows] == ["b"]
    assert f"container={STOPPED.name}" in one(narrowed, "#logs").get("sse-connect")
    none(_html(client, PAGE), "#logs-containers")  # the cache has one


def test_a_picked_range_narrows_the_stream_too(client: TestClient) -> None:
    """A line written after a picked bar's range is not added to it."""
    bars = select(_html(client, f"{PAGE}?window=0"), "#logs-volume a")
    narrowed = _html(client, bars[0].get("href"))
    stream = one(narrowed, "#logs").get("sse-connect")
    assert f"from={bars[0].get('data-from')}" in stream
    assert f"to={bars[0].get('data-to')}" in stream
