"""The Flet Container section: the same rows as the htmx Container section
(``ui_runtime.containers``), added to every component modal that has a
container behind it by ``BaseDetailPopup`` itself."""

from unittest.mock import MagicMock

import flet as ft
import pytest

from app.components.frontend.dashboard.modals import container_section
from app.components.frontend.dashboard.modals.base_detail_popup import BaseDetailPopup
from app.components.frontend.dashboard.modals.container_section import (
    ContainerSection,
)
from app.components.frontend.dashboard.modals.logs_section import LogsSection
from app.components.frontend.dashboard.modals.modal_sections import (
    DateRangeChips,
    LineChartCard,
)
from app.core import series
from app.services.system import ui_runtime
from app.services.system.models import ComponentStatus
from tests._fake_runtime import REDIS, FakeRuntime, use_runtime
from tests.components.frontend._fakes import FakePage
from tests.components.frontend._tree import texts, walk


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
    assert len(charts) == 2  # CPU and memory
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
    from app.components.frontend.controls.tabs import PulseTabs

    tabs = PulseTabs(tabs=[ft.Tab(text="Overview", content=ft.Text("x"))])
    component = ComponentStatus(name="cache", message="", metadata={})
    BaseDetailPopup(FakePage(), component, "Title", sections=[tabs], scrollable=False)  # type: ignore[arg-type]
    assert [t.text for t in tabs.tabs] == ["Overview", "Container", "Logs"]
    assert any(isinstance(c, ContainerSection) for c in walk(tabs.tabs[1]))
    assert any(isinstance(c, LogsSection) for c in walk(tabs.tabs[2]))


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


async def test_each_container_has_a_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Restart that confirms before it calls the API."""
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    section = ContainerSection("redis")
    await section.load()
    assert _restarts(section)


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
