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
from tests._fake_runtime import REDIS, WORKER, FakeRuntime, use_runtime
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
        "error",
        "Write failed",
        "Traceback (most recent call last):\nOSError: disk full",
    ]


def test_buttons_scroll_to_either_end(client: TestClient) -> None:
    targets = [
        b.get("data-scroll-to")
        for b in select(_html(client, PAGE), "#logs [data-scroll-to]")
    ]
    assert targets == ["#logs-lines > tr:first-child", "#logs-lines > tr:last-child"]


def test_the_filters_narrow_the_lines_and_keep_their_state(client: TestClient) -> None:
    html = _html(client, f"{PAGE}?level=error&window=3600&q=write")
    assert [
        text(one(row, "[data-message]")) for row in select(html, "#logs-lines tr")
    ] == ["Write failed"]
    assert checked(html, '#logs input[name="window"]') == ["3600"]
    assert (
        one(html, '#logs select[name="level"] option[selected]').get("value") == "error"
    )
    assert one(html, "#logs").get("sse-connect") == (
        "/overseer/events/logs/redis?level=error&q=write&order=desc"
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
    assert [text(one(r, "[data-message]")) for r in select(html, "#logs-lines tr")] == [
        "Task done"
    ]
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


def test_the_lead_the_columns_repeat_is_dimmed_but_copied(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign_in(app, monkeypatch, status_with(CACHE))
    lines = {REDIS.name: [_at(7, "2026-10-03 20:45:07 [info ] Started")]}
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=lines))
    (row,) = select(_html(TestClient(app), PAGE), "#logs-lines tr")
    assert text(one(row, "[data-prefix]")) == "2026-10-03 20:45:07 [info ]"
    assert text(one(row, "[data-message]")) == "Started"
    copies = [b.get("data-copy") for b in select(row, "[data-copy]")]
    assert "2026-10-03 20:45:07 [info ] Started" in copies


def test_the_search_is_marked_in_the_lines(client: TestClient) -> None:
    (row,) = select(_html(client, f"{PAGE}?q=write"), "#logs-lines tr")
    assert text(one(row, "[data-message] mark")) == "Write"


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
