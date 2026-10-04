"""A page's logs (``ui_logs``), as Overseer shows them in htmx and Flet
alike: every container's lines merged by time, JSON lines read as level,
event and fields, a traceback folded into the line it belongs to, the
level / text / time filters, and following new lines as they come."""

import json
from typing import Any

import pytest

from app.core import runtime
from app.core.runtime import LogLine, parse_log_line
from app.services.system import ui_logs
from tests._fake_runtime import REDIS, STOPPED, WORKER, FakeRuntime, use_runtime

SYSTEM, MEDIA = WORKER.name, STOPPED.name  # the worker page's two containers


def _at(second: int, text: str) -> LogLine:
    """A line as Docker sends it: its timestamp first."""
    return parse_log_line(f"2026-10-03T20:45:{second:02d}.000000000Z {text}", "stdout")


def _messages(view: dict[str, Any]) -> list[tuple[str, str]]:
    return [(row["instance"], row["message"]) for row in view["lines"]]


async def test_every_containers_lines_merge_by_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lines = {SYSTEM: [_at(1, "a"), _at(3, "c")], MEDIA: [_at(2, "b")]}
    use_runtime(monkeypatch, FakeRuntime(WORKER, STOPPED, lines=lines))
    view = await ui_logs.recent(["worker"], {"order": "asc"})
    assert _messages(view) == [(SYSTEM, "a"), (MEDIA, "b"), (SYSTEM, "c")]
    assert view["lines"][0]["at"] == "20:45:01"


async def test_the_newest_line_comes_first_unless_asked_otherwise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lines = {REDIS.name: [_at(1, "first"), _at(2, "second")]}
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=lines))
    newest = await ui_logs.recent(["redis"], {})
    oldest = await ui_logs.recent(["redis"], {"order": "asc"})
    assert [row["message"] for row in newest["lines"]] == ["second", "first"]
    assert [row["message"] for row in oldest["lines"]] == ["first", "second"]
    assert ui_logs.order_of({}) == "desc" and ui_logs.order_of({"order": "x"}) == "desc"


async def test_a_json_line_reads_as_level_event_and_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = {
        "level": "error",
        "event": "Payment failed",
        "order": 7,
        "exception": 'Traceback (most recent call last):\n  File "pay.py"\nValueError: x',
    }
    lines = {REDIS.name: [_at(1, json.dumps(record))]}
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=lines))
    (row,) = (await ui_logs.recent(["redis"], {}))["lines"]
    assert (row["level"], row["message"]) == ("error", "Payment failed")
    assert row["fields"] == [("order", "7")]
    assert "ValueError: x" in row["trace"]


async def test_a_plain_traceback_folds_into_its_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = [
        "ERROR: Exception in ASGI application",
        "Traceback (most recent call last):",
        '  File "app/main.py", line 3, in handler',
        "    raise ValueError('boom')",
        "ValueError: boom",
        "INFO: next request",
    ]
    lines = {REDIS.name: [_at(i, text) for i, text in enumerate(raw)]}
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=lines))
    first, second = (await ui_logs.recent(["redis"], {"order": "asc"}))["lines"]
    assert first["message"] == "Exception in ASGI application"
    assert (
        'File "app/main.py"' in first["trace"] and "ValueError: boom" in first["trace"]
    )
    assert (second["message"], second["trace"]) == ("next request", None)


async def test_the_level_and_text_filters_narrow_the_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lines = {
        REDIS.name: [
            _at(1, json.dumps({"level": "info", "event": "Started"})),
            _at(2, json.dumps({"level": "warning", "event": "Slow query"})),
            _at(3, json.dumps({"level": "error", "event": "Query failed"})),
            _at(4, "plain text with no level"),
        ]
    }
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=lines))
    warned = await ui_logs.recent(["redis"], {"level": "warning", "order": "asc"})
    assert [row["message"] for row in warned["lines"]] == ["Slow query", "Query failed"]
    found = await ui_logs.recent(["redis"], {"q": "QUERY", "order": "asc"})
    assert [row["message"] for row in found["lines"]] == ["Slow query", "Query failed"]


async def test_the_window_reads_from_its_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same compact labels as every other range row; All reads from the
    container's start."""
    assert [label for _, label in ui_logs.WINDOWS] == ["15m", "1h", "6h", "1d", "All"]
    fake = use_runtime(monkeypatch, FakeRuntime(REDIS))
    await ui_logs.recent(["redis"], {"window": "3600"})
    await ui_logs.recent(["redis"], {"window": str(ui_logs.ALL)})
    (_, _, hour), (_, _, everything) = fake.logged
    assert hour is not None and everything is None


async def test_without_a_container_it_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS, backend_name="none"))
    view = await ui_logs.recent(["redis"], {})
    assert view["lines"] == [] and "aegis add deploy" in view["note"]


async def test_following_merges_the_containers_and_folds_tracebacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    followed = {
        SYSTEM: [
            _at(1, "Task failed"),
            _at(1, "Traceback (most recent call last):"),
            _at(1, "ValueError: boom"),
        ],
        MEDIA: [_at(2, "Media ready")],
    }
    use_runtime(monkeypatch, FakeRuntime(WORKER, STOPPED, followed=followed))
    rows = [row async for batch in ui_logs.follow(["worker"], {}) for row in batch]
    failed = next(row for row in rows if row["message"] == "Task failed")
    assert "ValueError: boom" in failed["trace"]
    assert sorted(row["message"] for row in rows) == ["Media ready", "Task failed"]


async def test_several_pages_read_as_one_view(monkeypatch: pytest.MonkeyPatch) -> None:
    """Overseer > Logs: every page's containers merged by time, each line
    naming the page it belongs to."""
    lines = {REDIS.name: [_at(1, "cache up")], SYSTEM: [_at(2, "task done")]}
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER, lines=lines))
    view = await ui_logs.recent(["redis", "worker"], {})
    assert [(row["page"], row["message"]) for row in view["lines"]] == [
        ("worker", "task done"),
        ("redis", "cache up"),
    ]


async def test_the_sources_are_the_pages_with_a_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER))
    assert await ui_logs.sources() == [
        {"page": "redis", "title": "Cache"},
        {"page": "worker", "title": "Worker"},
    ]


@pytest.mark.parametrize(
    ("raw", "prefix", "message"),
    [
        (
            "2026-10-04 02:13:18 [info ] Active LLM",
            "2026-10-04 02:13:18 [info ] ",
            "Active LLM",
        ),
        (
            "[2026-10-04 02:13:18,198][taskiq.worker][INFO ][MainProcess] Started",
            "[2026-10-04 02:13:18,198][taskiq.worker][INFO ][MainProcess] ",
            "Started",
        ),
        ("INFO:     127.0.0.1 - GET /health", "INFO:     ", "127.0.0.1 - GET /health"),
        ("[02:13:16] 1 change detected", "[02:13:16] ", "1 change detected"),
        (
            "2026-10-04 02:13:18.123 UTC [1] LOG:  checkpoint",
            "2026-10-04 02:13:18.123 UTC [1] ",
            "LOG:  checkpoint",
        ),
        ("2026-10-04 02:13:18 the end", "2026-10-04 02:13:18 ", "the end"),
        ("plain words", "", "plain words"),
        ("2026-10-04 02:13:18 ", "", "2026-10-04 02:13:18 "),  # nothing after it
    ],
)
async def test_the_lead_the_columns_repeat_is_split_off(
    monkeypatch: pytest.MonkeyPatch, raw: str, prefix: str, message: str
) -> None:
    """A plain line's leading time and level (which the time and level
    columns already show) as ``prefix``, kept so the UIs can dim it and a
    copy can keep it."""
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines={REDIS.name: [_at(1, raw)]}))
    (row,) = (await ui_logs.recent(["redis"], {}))["lines"]
    assert (row["prefix"], row["message"]) == (prefix, message)


async def test_each_service_keeps_one_color(monkeypatch: pytest.MonkeyPatch) -> None:
    """An index into the shared chart ramp, the same for a service on every
    page and in both UIs, and different for every service."""
    colors = {page: ui_logs.color_of(page) for page in runtime.PAGES}
    assert len(set(colors.values())) == len(colors)
    assert all(0 <= c < ui_logs.RAMP for c in colors.values())
    lines = {REDIS.name: [_at(1, "up")]}
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=lines))
    (row,) = (await ui_logs.recent(["redis"], {}))["lines"]
    assert row["color"] == colors["redis"]
