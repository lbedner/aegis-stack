"""The Flet Logs section: the same lines as the htmx section (``ui_logs``),
filtered the same way and following new lines while the modal is open;
added to every component modal with a container behind it, after
Container."""

import json
from unittest.mock import MagicMock

import pytest

from app.components.frontend.controls.buttons import IconCopyButton
from app.components.frontend.dashboard.modals.logs_popup import LogsPopup
from app.components.frontend.dashboard.modals.logs_section import LogsSection, _line
from app.components.frontend.dashboard.modals.modal_sections.chart_primitives import (
    ChartColors,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.runtime import LogLine, parse_log_line
from app.services.system import ui_logs
from tests._fake_runtime import (
    REDIS,
    WORKER,
    FakeRuntime,
    container_lookups,
    use_runtime,
)
from tests.components.frontend._tree import texts, walk


def _at(second: int, text: str) -> LogLine:
    return parse_log_line(f"2026-10-03T20:45:{second:02d}.000000000Z {text}", "stdout")


LINES = {
    REDIS.name: [
        _at(1, json.dumps({"level": "info", "event": "Ready to accept connections"})),
        _at(2, json.dumps({"level": "error", "event": "Write failed"})),
        _at(3, "Traceback (most recent call last):"),
        _at(3, "OSError: disk full"),
    ]
}


async def test_it_lists_the_lines_with_their_traceback_folded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=LINES))
    section = LogsSection("redis")
    await section.load()
    shown = texts(section)
    assert "Ready to accept connections" in shown and "Write failed" in shown
    assert any("OSError: disk full" in t for t in shown)


async def test_the_level_filter_narrows_the_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=LINES))
    section = LogsSection("redis")
    await section.show({"level": "error"})
    shown = texts(section)
    assert "Write failed" in shown and "Ready to accept connections" not in shown


async def test_following_appends_new_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    followed = {REDIS.name: [_at(4, json.dumps({"level": "info", "event": "Saved"}))]}
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=LINES, followed=followed))
    section = LogsSection("redis")
    await section.load()
    await section.follow()
    assert "Saved" in texts(section)


async def test_without_a_container_it_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS, backend_name="none"))
    section = LogsSection("redis")
    await section.load()
    assert any("aegis add deploy" in t for t in texts(section))


async def test_the_newest_line_comes_first_unless_asked_otherwise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=LINES))
    section = LogsSection("redis")
    await section.load()
    shown = texts(section)
    assert shown.index("Write failed") < shown.index("Ready to accept connections")
    await section.show({"order": "asc"})
    shown = texts(section)
    assert shown.index("Ready to accept connections") < shown.index("Write failed")


async def test_a_followed_line_joins_at_the_top(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    followed = {REDIS.name: [_at(4, json.dumps({"level": "info", "event": "Saved"}))]}
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=LINES, followed=followed))
    section = LogsSection("redis")
    await section.load()
    await section.follow()
    assert "Saved" in texts(section._lines.controls[0])


async def test_every_line_copies_what_it_shows(monkeypatch: pytest.MonkeyPatch) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=LINES))
    section = LogsSection("redis")
    await section.load()
    first = section._lines.controls[0]
    (button,) = [n for n in walk(first) if isinstance(n, IconCopyButton)]
    copied = button.get_text()
    assert "Write failed" in copied and "OSError: disk full" in copied


# Overseer > Logs in Flet: every service's lines, from the header.
EVERY = {
    REDIS.name: LINES[REDIS.name],
    WORKER.name: [_at(5, json.dumps({"level": "info", "event": "Task done"}))],
}


async def test_every_service_reads_as_one_view_naming_each_lines_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER, lines=EVERY))
    section = LogsSection()
    await section.load()
    first = texts(section._lines.controls[0])
    assert "Task done" in first and "Worker" in first
    assert "Cache" in texts(section._lines.controls[1])


async def test_the_service_filter_narrows_the_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER, lines=EVERY))
    section = LogsSection()
    await section.pick_services({"worker"})
    shown = texts(section)
    assert "Task done" in shown and "Write failed" not in shown


async def test_paused_it_adds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    followed = {REDIS.name: [_at(4, json.dumps({"level": "info", "event": "Saved"}))]}
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=LINES, followed=followed))
    section = LogsSection("redis")
    await section.load()
    section.paused = True
    await section.follow()
    assert "Saved" not in texts(section)


def test_the_logs_popup_holds_every_services_logs() -> None:
    popup = LogsPopup(page=MagicMock())
    assert any(isinstance(n, LogsSection) for n in walk(popup))


def _row(**given: object) -> dict[str, object]:
    row = {
        "at": "20:45:01",
        "page": "redis",
        "instance": REDIS.name,
        "source": "",
        "level": None,
        "prefix": "",
        "message": "Write failed",
        "fields": [],
        "trace": None,
        "color": 0,
    }
    return row | given


def test_a_warning_or_worse_has_a_stripe_in_its_color() -> None:
    assert _line(_row(level="error")).border.left.color == Theme.Colors.ERROR
    assert _line(_row(level="info")).border is None


def test_the_lead_is_left_out_and_the_search_marked() -> None:
    """The time and level the line's own lead repeats are shown once."""
    line = _line(_row(prefix="[02:13:16] ", message="Write failed"), query="write")
    spans = [n for node in walk(line) for n in (getattr(node, "spans", None) or [])]
    assert [s.text for s in spans] == ["Write", " failed"]
    assert spans[0].style.bgcolor is not None and spans[1].style is None


def test_a_line_names_its_container_only_where_its_service_has_several() -> None:
    """One source: the service, then which of its containers when it has
    several (``source``), as the htmx page shows it."""
    alone = texts(_line(_row(), titles={"redis": "Cache"}))
    assert REDIS.name not in alone
    several = texts(_line(_row(source="system"), titles={"redis": "Cache"}))
    assert "system" in several


def test_each_service_has_its_own_color() -> None:
    line = _line(_row(color=3), titles={"redis": "Cache"})
    (dot,) = [n for n in walk(line) if getattr(n, "data", None) == "service-dot"]
    assert dot.bgcolor == ChartColors.RAMP[3]


def test_the_level_picker_offers_what_the_page_does() -> None:
    """The levels htmx offers, lines with none among them, from one list."""
    import flet as ft

    picker = next(
        n
        for n in walk(LogsSection("redis"))
        if isinstance(n, ft.Dropdown) and any(o.key == "error" for o in n.options)
    )
    keys = [o.key for o in picker.options]
    assert keys[1:] == [value for value, _ in ui_logs.LEVEL_CHOICES]


async def test_every_services_load_looks_its_containers_up_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The service menu and the lines read the same containers."""
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER, lines=LINES))
    seen = container_lookups(monkeypatch)
    await LogsSection().load()
    assert len(seen) == 1


async def test_a_pages_load_and_follow_look_its_containers_up_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS, lines=LINES))
    seen = container_lookups(monkeypatch)
    section = LogsSection("redis")
    await section.load()
    await section.follow()
    assert len(seen) == 1
