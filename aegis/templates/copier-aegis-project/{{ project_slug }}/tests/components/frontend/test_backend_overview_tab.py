"""The Flet backend modal's host meters colour by each check's status (the
saved thresholds' rule, ``app.core.thresholds``), as htmx's do: not by
numbers of their own."""

import flet as ft

from app.components.frontend.dashboard.modals.backend_modal.overview_tab import (
    OverviewTab,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus, ComponentStatusType
from tests.components.frontend._tree import walk


def test_a_meter_takes_its_checks_status_colour() -> None:
    """At 50%, under any fixed line, but the check says warning."""
    cpu = ComponentStatus(
        name="cpu",
        message="",
        status=ComponentStatusType.WARNING,
        metadata={"percent_used": 50.0, "cpu_count": 4},
    )
    backend = ComponentStatus(
        name="backend", message="", metadata={}, sub_components={"cpu": cpu}
    )
    (bar,) = [n for n in walk(OverviewTab(backend)) if isinstance(n, ft.ProgressBar)]
    assert bar.color == Theme.Colors.WARNING
