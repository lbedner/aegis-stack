"""The Stack view's component list: as tall as the window lets it be, and
scrolled inside itself (as the activity feed beside it is), so a stack
with more parts than fit is still read to its end."""

from unittest.mock import MagicMock

import flet as ft

from app.components.frontend.dashboard.status_overview import StatusOverviewPanel
from app.components.frontend.overseer.body import DashboardViews
from app.services.system.models import ComponentStatus
from tests.components.frontend._tree import walk


def _lists(panel: StatusOverviewPanel) -> list[ft.ListView]:
    return [n for n in walk(panel) if isinstance(n, ft.ListView)]


def _parts(status: str) -> dict[str, ComponentStatus]:
    return {
        f"part_{i}": ComponentStatus(name=f"part_{i}", status=status, message="ok")
        for i in range(30)
    }


def test_the_list_scrolls_inside_itself() -> None:
    panel = StatusOverviewPanel()
    panel.update_components(_parts("healthy"))
    assert panel.expand
    (rows,) = _lists(panel)
    assert rows.expand


def test_a_refresh_keeps_its_place() -> None:
    """New statuses fill the same list, so a reader scrolled down it is not
    sent back to the top (nor a click to the row now under the pointer)."""
    panel = StatusOverviewPanel()
    panel.update_components(_parts("healthy"))
    (rows,) = _lists(panel)

    panel.update_components(_parts("unhealthy"))

    assert _lists(panel) == [rows]


def test_the_stack_view_gives_it_the_window_height() -> None:
    views = DashboardViews(MagicMock(), MagicMock(), ft.IconButton())
    (column,) = [
        n
        for n in walk(views.stack_view_container)
        if isinstance(n, ft.Container) and n.content is views.status_overview_panel
    ]
    assert column.expand
