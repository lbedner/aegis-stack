"""The Flet Container section: the same rows as the htmx Container section
(``ui_runtime.containers``), added to every component modal that has a
container behind it by ``BaseDetailPopup`` itself."""

from unittest.mock import MagicMock

import flet as ft
import pytest

from app.components.frontend.controls import DataTable, H3Text
from app.components.frontend.controls.expand_arrow import EXPAND_ICON_WIDTH
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.dashboard.modals import container_section
from app.components.frontend.dashboard.modals.base_detail_popup import (
    RUNTIME_WIDTH,
    BaseDetailPopup,
)
from app.components.frontend.dashboard.modals.container_section import (
    ContainerSection,
)
from app.components.frontend.dashboard.modals.logs_section import LogsSection
from app.components.frontend.dashboard.modals.modal_constants import ModalLayout
from app.components.frontend.dashboard.modals.modal_sections import (
    DateRangeChips,
    LineChartCard,
)
from app.components.frontend.dashboard.modals.table_tab import ACTIONS_WIDTH
from app.components.frontend.theme import AegisTheme as Theme
from app.core import series
from app.services.shared.deps import NO_AUTH_REFUSAL
from app.services.system import ui_runtime
from app.services.system.models import ComponentStatus
from tests._fake_runtime import REDIS, FakeRuntime, use_runtime
from tests.components.frontend._fakes import FakePage
from tests.components.frontend._tree import tab_names, tabs_in, texts, walk


async def test_it_stops_reading_when_the_tab_goes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flet keeps a closed tab's session for an hour; nothing reads for it."""
    monkeypatch.setattr(
        container_section, "SessionLoops", lambda *_: MagicMock(alive=lambda: False)
    )
    section = ContainerSection("redis")
    section._open = True
    reads: list[None] = []

    async def load() -> None:
        reads.append(None)

    monkeypatch.setattr(section, "load", load)
    await section._keep_reading()

    assert reads == []


def test_it_says_it_is_reading_until_the_first_read_lands() -> None:
    assert "Reading the containers." in texts(ContainerSection("redis"))


async def test_it_lists_the_containers(monkeypatch: pytest.MonkeyPatch) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    section = ContainerSection("redis")
    await section.load()
    shown = " ".join(texts(section))
    assert "app-redis-1" in shown and "12.5%" in shown


async def test_it_charts_what_was_sampled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same charts as the htmx section, from the same sampled series."""
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    page = f"{ui_runtime.SAMPLER}:redis:app-redis-1"
    await series.record(
        {f"{page}:{ui_runtime.CPU}": 12.5, f"{page}:{ui_runtime.MEMORY}": 2048.0}
    )
    section = ContainerSection("redis")
    await section.load()
    charts = [c for c in walk(section) if isinstance(c, LineChartCard)]
    assert len(charts) == 3  # CPU, memory and processes (0, from the sample)
    assert "app-redis-1" in texts(charts[0])  # its legend


async def test_the_range_chips_pick_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    asked: list[int] = []
    charts = ui_runtime.charts

    async def charted(
        page: str, window: int = series.DEFAULT_WINDOW, *rest: object
    ) -> object:
        asked.append(window)
        return await charts(page, window, *rest)  # type: ignore[arg-type]

    monkeypatch.setattr(ui_runtime, "charts", charted)
    section = ContainerSection("redis")
    await section.load()
    (chips,) = [c for c in walk(section) if isinstance(c, DateRangeChips)]
    await section.show_window(1800)
    assert asked == [series.DEFAULT_WINDOW, 1800]


async def test_no_range_chips_without_charts(monkeypatch: pytest.MonkeyPatch) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS, backend_name="none"))
    section = ContainerSection("redis")
    await section.load()
    assert not [c for c in walk(section) if isinstance(c, DateRangeChips)]


def test_the_modal_reads_inside_the_watch() -> None:
    """Each refresh renews the watch before it lapses, so the sampler keeps
    its full pace while the modal is open."""
    from app.components.frontend.dashboard.modals import container_section

    assert container_section.REFRESH_SECONDS < series.WATCH_SECONDS


def test_a_tabbed_modal_gets_a_container_tab() -> None:
    """A popup whose body is a tab bar (not scrolled) takes the section as a
    tab, rather than below the tabs in a column that cannot scroll."""
    tabs = PulseTabs(tabs=[ft.Tab(text="Overview", content=ft.Text("x"))])
    component = ComponentStatus(name="cache", message="", metadata={})
    BaseDetailPopup(FakePage(), component, "Title", sections=[tabs], scrollable=False)  # type: ignore[arg-type]
    assert tab_names(tabs) == ["Overview", "Container", "Logs"]
    assert any(isinstance(c, ContainerSection) for c in walk(tabs.tabs[1]))
    assert any(isinstance(c, LogsSection) for c in walk(tabs.tabs[2]))
    # The tab names it: no heading repeats the name inside.
    for tab in tabs.tabs[1:]:
        assert not [c for c in walk(tab.content) if isinstance(c, H3Text)]


def test_a_modal_without_tabs_gets_its_container_and_logs_as_tabs() -> None:
    """Its own sections are its first tab, Container and Logs beside it,
    tall enough to read them."""
    component = ComponentStatus(name="cache", message="", metadata={})
    popup = BaseDetailPopup(  # type: ignore[arg-type]
        FakePage(), component, "Title", sections=[ft.Text("own")], height=340
    )
    tabs = tabs_in(popup)
    assert tab_names(popup) == ["Overview", "Container", "Logs"]
    assert "own" in texts(tabs.tabs[0])
    assert popup.panel.height >= ModalLayout.DEFAULT_HEIGHT
    # The Logs tab is its lines, which scroll themselves; the tab does not.
    logs_page = next(n for n in walk(tabs.tabs[2]) if isinstance(n, ft.Column))
    assert logs_page.scroll is None


def test_a_modal_with_its_container_is_big_enough_to_read_it() -> None:
    """The container's columns and its logs need the room
    (``RUNTIME_WIDTH``): a smaller modal, tabbed or not, grows to it."""
    tabs = PulseTabs(tabs=[ft.Tab(text="Overview", content=ft.Text("x"))])
    component = ComponentStatus(name="cache", message="", metadata={})
    popup = BaseDetailPopup(  # type: ignore[arg-type]
        FakePage(),
        component,
        "T",
        sections=[tabs],
        scrollable=False,
        width=900,
        height=550,
    )
    assert popup.panel.width >= RUNTIME_WIDTH
    assert popup.panel.height >= ModalLayout.DEFAULT_HEIGHT


async def test_a_chart_with_nothing_in_its_window_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS))

    async def nothing(*_: object, **__: object) -> dict[str, object]:
        return {}

    monkeypatch.setattr(series, "read", nothing)
    section = ContainerSection("redis")
    await section.load()
    assert not [c for c in walk(section) if isinstance(c, LineChartCard)]
    assert any("Nothing in the last 15 minutes" in t for t in texts(section))


async def test_without_a_deploy_target_it_says_what_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS, backend_name="none"))
    section = ContainerSection("redis")
    await section.load()
    assert any("aegis add deploy" in t for t in texts(section))


def _popup(name: str) -> BaseDetailPopup:
    component = ComponentStatus(name=name, message="", metadata={})
    return BaseDetailPopup(FakePage(), component, "Title", sections=[])  # type: ignore[arg-type]


def test_a_component_with_a_container_gets_the_section() -> None:
    assert any(isinstance(c, ContainerSection) for c in walk(_popup("cache")))


def test_one_without_a_container_does_not() -> None:
    assert not any(isinstance(c, ContainerSection) for c in walk(_popup("auth")))


def test_an_events_chart_draws_dots_not_a_line() -> None:
    """A call is a moment: no line between two of them (``"style": "events"``)."""
    data = {
        "labels": [1_000, 2_000],
        "series": [{"label": "qwen2.5:7b", "values": [8.0, 16.0]}],
        "x": "time",
        "format": None,
        "style": "events",
    }
    (chart,) = [
        c
        for c in walk(LineChartCard.from_chart("Tokens per second", data))
        if isinstance(c, ft.LineChart)
    ]
    (line, *_) = chart.data_series
    assert line.stroke_width == 0
    assert all(p.point for p in line.data_points)


def _opened_where(monkeypatch: pytest.MonkeyPatch, refused: str | None) -> None:
    """The dashboard opened where a change is ``refused`` (None: allowed;
    ``page_refusal``'s rule is tested on its own)."""
    monkeypatch.setattr(container_section, "page_refusal", lambda page: refused)


async def test_each_container_has_a_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Restart that confirms before it calls the API."""
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    _opened_where(monkeypatch, None)
    section = ContainerSection("redis")
    await section.load()
    assert _restarts(section)


async def test_where_a_change_is_refused_no_restart_and_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opened where the dashboard may not make a change
    (``page_refusal``), the button is not offered."""
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    _opened_where(monkeypatch, NO_AUTH_REFUSAL)
    section = ContainerSection("redis")
    await section.load()
    assert not _restarts(section)
    assert NO_AUTH_REFUSAL in texts(section)


def _restarts(section: ContainerSection) -> list[ft.IconButton]:
    """The rows' Restart buttons (a table cell drops its tooltip, so by icon)."""
    return [
        n
        for n in walk(section)
        if isinstance(n, ft.IconButton) and n.icon == ft.Icons.RESTART_ALT
    ]


async def test_restart_calls_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[str] = []

    class Api:
        async def post(self, url: str) -> dict[str, str]:
            posted.append(url)
            return {"restarted": REDIS.name}

    monkeypatch.setattr(
        container_section, "get_session_state", lambda page: MagicMock(api_client=Api())
    )
    page = MagicMock()
    await container_section.restart(page, REDIS.name)
    assert posted == [ui_runtime.RESTART_API.format(name=REDIS.name)]
    page.open.assert_called_once()  # the snackbar saying it restarted


def test_a_chart_draws_where_warning_begins_as_a_dashed_guide() -> None:
    """The htmx chart's dashed lines: each threshold the server sent (those
    in reach, ``series.thresholds_in_reach``), across the chart, out of the
    legend, and inside the axis."""
    data = {
        "labels": [1_000, 2_000],
        "series": [{"label": "app-redis-1", "values": [5.0, 8.0]}],
        "x": "time",
        "format": "percent",
        "thresholds": [{"value": 12, "tone": "warn"}],
    }
    card = LineChartCard.from_chart("CPU", data)
    (chart,) = [c for c in walk(card) if isinstance(c, ft.LineChart)]
    line, guide = chart.data_series
    assert guide.dash_pattern and guide.color == Theme.Colors.WARNING
    assert [(p.x, p.y) for p in guide.data_points] == [(0, 12), (1, 12)]
    assert chart.max_y >= 12


def _reading_one_row(monkeypatch: pytest.MonkeyPatch, **given: str) -> ContainerSection:
    """A section whose every reading is one row: ``given`` over an ``x`` in
    each column."""
    row = {key: "x" for _, key, _ in container_section.COLUMNS} | given

    async def section(*_: object, **__: object) -> tuple:
        return {"rows": [row], "note": None}, []

    monkeypatch.setattr(ui_runtime, "section", section)
    return ContainerSection("redis")


async def test_a_figure_past_its_threshold_takes_its_tone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The htmx section's colours: CPU at a warning in amber, memory at the
    alert in red, a figure under its threshold plain."""
    shown = _reading_one_row(
        monkeypatch,
        cpu="95%",
        memory="1 GB",
        disk="9 B/s",
        cpu_status="warning",
        memory_status="unhealthy",
    )
    await shown.load()
    colors = {
        n.value: n.color for n in walk(shown) if isinstance(n, ft.Text) and n.value
    }
    assert colors["95%"] == Theme.Colors.WARNING
    assert colors["1 GB"] == Theme.Colors.ERROR
    assert colors["9 B/s"] == ft.Colors.ON_SURFACE


# What a container's name needs to be read.
NAME_ROOM = 160


def test_the_fixed_columns_leave_the_name_room() -> None:
    """Everything the table takes but the name: its fixed columns, Restart,
    the arrow a row opens by, a gap between every two cells and the row's
    own padding; inside the narrowest modal it opens in, past that modal's
    padding and the tab's."""
    fixed = [width for _, _, width in container_section.COLUMNS if width]
    cells = len(container_section.COLUMNS) + 2  # Restart, the arrow
    taken = sum(fixed) + ACTIONS_WIDTH + EXPAND_ICON_WIDTH
    taken += Theme.Spacing.MD * (cells - 1) + Theme.Spacing.MD * 2
    room = RUNTIME_WIDTH - 2 * ModalLayout.CONTENT_PADDING - 2 * Theme.Spacing.MD
    assert room - taken >= NAME_ROOM


async def test_an_opened_row_stays_open_when_it_reads_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The section reads its containers again every few seconds: a row the
    reader opened stays open, in the same table."""
    shown = _reading_one_row(monkeypatch, image="aegis-stack-my-app:latest")
    await shown.load()
    (table,) = [n for n in walk(shown) if isinstance(n, DataTable)]
    table._toggle_expand(0)

    await shown.load()

    assert [n for n in walk(shown) if isinstance(n, DataTable)] == [table]
    assert "aegis-stack-my-app:latest" in texts(table)


async def test_a_row_opens_to_its_image(monkeypatch: pytest.MonkeyPatch) -> None:
    """A long image name is no column of its own: a row opens to it, and to
    the figures its columns may cut short."""
    image, disk = "aegis-stack-my-app:latest", "read 25.1 MB, write 47.7 MB"
    shown = _reading_one_row(monkeypatch, image=image, disk=disk)
    await shown.load()
    assert "image" not in [key for _, key, _ in container_section.COLUMNS]
    (table,) = [n for n in walk(shown) if isinstance(n, DataTable)]
    opened = texts(table._expandable_content(0))
    assert image in opened and disk in opened
