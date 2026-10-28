"""The Flet backend modal's Overview, as htmx's: with containers to read,
the server's own live charts (``ui_runtime.OVERVIEW_CHARTS``); without,
the host's meters, coloured by each check's status (the saved thresholds'
rule, ``app.core.thresholds``), not by numbers of their own."""

import flet as ft
import pytest

from app.components.frontend.controls import DataTable
from app.components.frontend.dashboard.modals.backend_modal.overview_tab import (
    OverviewTab,
)
from app.components.frontend.dashboard.modals.container_section import (
    ContainerSection,
)
from app.components.frontend.dashboard.modals.modal_sections import LineChartCard
from app.components.frontend.theme import AegisTheme as Theme
from app.core import series
from app.services.system import ui_runtime
from app.services.system.models import ComponentStatus, ComponentStatusType
from tests._fake_runtime import SERVER, FakeRuntime, use_runtime
from tests.components.frontend._tree import walk

CPU = ComponentStatus(
    name="cpu",
    message="",
    status=ComponentStatusType.WARNING,
    metadata={"percent_used": 50.0, "cpu_count": 4},
)
BACKEND = ComponentStatus(
    name="backend", message="", metadata={}, sub_components={"cpu": CPU}
)


def test_a_meter_takes_its_checks_status_colour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No containers to read; at 50%, under any fixed line, but the check
    says warning."""
    use_runtime(monkeypatch, FakeRuntime(backend_name="none"))
    (bar,) = [n for n in walk(OverviewTab(BACKEND)) if isinstance(n, ft.ProgressBar)]
    assert bar.color == Theme.Colors.WARNING


async def test_with_containers_it_charts_the_server_not_the_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What it runs on, live: the Container section's charts, only the
    Overview's (processes stay on the Container tab), and no table."""
    use_runtime(monkeypatch, FakeRuntime(SERVER))
    page = f"{ui_runtime.SAMPLER}:server:app-webserver-1"
    await series.record(
        {f"{page}:{ui_runtime.CPU}": 12.5, f"{page}:{ui_runtime.MEMORY}": 2048.0}
    )
    tab = OverviewTab(BACKEND)
    assert not [n for n in walk(tab) if isinstance(n, ft.ProgressBar)]
    (section,) = [n for n in walk(tab) if isinstance(n, ContainerSection)]
    await section.load()
    assert not [n for n in walk(tab) if isinstance(n, DataTable)]
    assert len([n for n in walk(tab) if isinstance(n, LineChartCard)]) == 2
