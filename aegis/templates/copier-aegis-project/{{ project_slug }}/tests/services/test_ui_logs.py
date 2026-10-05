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
    from starlette.datastructures import QueryParams

    async def shown(query: str) -> list[str]:
        view = await ui_logs.recent(["redis"], QueryParams(query + "&order=asc"))
        return [row["message"] for row in view["lines"]]

    # Exactly the levels picked, not that level and worse.
    assert await shown("level=warning") == ["Slow query"]
    assert await shown("level=info&level=error") == ["Started", "Query failed"]
    assert await shown(f"level={ui_logs.NO_LEVEL}") == ["plain text with no level"]
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
        {"page": "redis", "title": "Cache", "containers": []},
        {"page": "worker", "title": "Worker", "containers": []},
    ]


async def test_a_source_with_several_containers_lists_each(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(WORKER, STOPPED))
    (worker,) = await ui_logs.sources()
    assert worker["containers"] == [
        {"name": SYSTEM, "label": "system"},
        {"name": MEDIA, "label": "media"},
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
    """A plain line's leading time and level (which the time cell and the
    level tag already show) as ``prefix``: the UIs leave it out, and a copy
    keeps it."""
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


async def test_a_line_names_its_container_only_where_its_service_has_several(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One source column: the worker's lines say which of its containers
    (what their names do not share), the cache's one container needs none."""
    lines = {SYSTEM: [_at(1, "a")], MEDIA: [_at(2, "b")], REDIS.name: [_at(3, "c")]}
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER, STOPPED, lines=lines))
    view = await ui_logs.recent(["worker", "redis"], {})
    assert {(row["message"], row["source"]) for row in view["lines"]} == {
        ("a", "system"),
        ("b", "media"),
        ("c", ""),
    }


def _json(level: str, event: str) -> str:
    return json.dumps({"level": level, "event": event})


async def test_the_volume_counts_the_windows_lines_by_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bar per slice of the window, its lines stacked by tone, so where
    things went wrong shows before a line is read."""
    lines = {
        REDIS.name: [
            _at(1, _json("info", "up")),
            _at(2, _json("error", "down")),
            _at(3, _json("warning", "slow")),
            _at(4, "plain"),
        ]
    }
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=lines))
    view = await ui_logs.recent(["redis"], {"window": str(ui_logs.ALL)}, volume=True)
    volume = view["volume"]
    assert len(volume) == ui_logs.VOLUME_BARS
    totals = {tone: sum(bar[tone] for bar in volume) for tone in ui_logs.VOLUME_TONES}
    assert totals == {"error": 1, "warn": 1, "other": 2}
    assert all(bar["from"] < bar["to"] for bar in volume)


async def test_a_bars_time_range_narrows_the_lines_but_not_the_volume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lines = {REDIS.name: [_at(1, "early"), _at(30, "late")]}
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=lines))
    late = lines[REDIS.name][1].timestamp
    assert late is not None
    start = ui_logs._ms(late)
    query = {"window": str(ui_logs.ALL), "from": str(start), "to": str(start + 1000)}
    view = await ui_logs.recent(["redis"], query, volume=True)
    assert [row["message"] for row in view["lines"]] == ["late"]
    assert sum(bar["other"] for bar in view["volume"]) == 2


async def test_a_picked_container_narrows_its_page_to_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``container``: of a page with several, only the ones picked; a page
    with none picked shows every container."""
    from starlette.datastructures import QueryParams

    lines = {SYSTEM: [_at(1, "a")], MEDIA: [_at(2, "b")], REDIS.name: [_at(3, "c")]}
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER, STOPPED, lines=lines))
    query = QueryParams({"container": SYSTEM})
    view = await ui_logs.recent(["worker", "redis"], query)
    assert sorted(row["message"] for row in view["lines"]) == ["a", "c"]
    # Read alone, it is still the worker's ``system``.
    assert {r["message"]: r["source"] for r in view["lines"]}["a"] == "system"
