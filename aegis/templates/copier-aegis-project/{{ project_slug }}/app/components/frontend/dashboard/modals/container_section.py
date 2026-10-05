"""The Container section every component modal with a container behind it
gets (``BaseDetailPopup`` adds it): the same rows as the htmx Container section
(``ui_runtime.containers``), read again while the modal is open. Each row
has a Restart that confirms, then calls the restart API (behind
``get_admin_actor``; it audits every attempt), as the htmx section's does."""

import asyncio
from typing import Any

import flet as ft

from app.components.frontend.controls import ConfirmDialog, H3Text, SecondaryText
from app.components.frontend.controls.snack_bar import ErrorSnackBar, SuccessSnackBar
from app.components.frontend.dashboard.cards.card_utils import get_status_color
from app.components.frontend.dashboard.modals.modal_sections import (
    DateRangeChips,
    LineChartCard,
)
from app.components.frontend.state.session_state import get_session_state
from app.components.frontend.theme import AegisTheme as Theme
from app.core import series
from app.services.system import ui_runtime

from .table_tab import TableTab

REFRESH_SECONDS = 5.0
# Each column's heading, ``ui_runtime`` row key and width.
COLUMNS = [
    ("Container", "name", None),
    ("State", "state", 130),
    (ui_runtime.FIGURES["cpu"], "cpu", 70),
    (ui_runtime.FIGURES["memory"], "memory", 150),
    (ui_runtime.FIGURES["network"], "network", 170),
    (ui_runtime.FIGURES["disk"], "disk", 170),
    ("Restarts", "restarts", 70),
    ("Up", "uptime", 80),
    ("Image", "image", 160),
]


class ContainerSection(ft.Column):
    """The containers behind one Overseer page (``page``: ``redis``, ...)."""

    def __init__(self, page: str) -> None:
        super().__init__(spacing=Theme.Spacing.SM)
        self._key = page
        self._open = False
        self._window = series.DEFAULT_WINDOW
        self._chips = DateRangeChips(
            options=[(label, seconds) for seconds, label in series.WINDOWS],
            selected_days=self._window,
            on_change=lambda seconds: self.page.run_task(self.show_window, seconds),
        )
        self._show(ui_runtime.PENDING)

    async def show_window(self, seconds: int) -> None:
        """Chart the last ``seconds`` (a range chip)."""
        self._window = seconds
        await self.load()

    def did_mount(self) -> None:
        self._open = True
        self.page.run_task(self._keep_reading)

    def will_unmount(self) -> None:
        self._open = False

    async def _keep_reading(self) -> None:
        while self._open:
            await self.load()
            await asyncio.sleep(REFRESH_SECONDS)

    async def load(self) -> None:
        view, charts = await ui_runtime.section(self._key, self._window)
        self._show(view, charts)
        if self.page is not None:
            self.update()

    def _restart_button(self, row: dict[str, str]) -> ft.Control:
        name = row["name"]
        return ft.IconButton(
            ft.Icons.RESTART_ALT,
            tooltip="Restart",
            icon_size=18,
            on_click=lambda _: ConfirmDialog(
                page=self.page,
                title=ui_runtime.RESTART_TITLE,
                message=ui_runtime.restart_confirm(name),
                confirm_text="Restart",
                on_confirm=lambda: restart(self.page, name),
            ).show(),
        )

    def _show(
        self, view: dict[str, Any], charts: list[dict[str, Any]] | None = None
    ) -> None:
        body: ft.Control = (
            SecondaryText(view["note"])
            if view["note"]
            else TableTab(
                view["rows"],
                COLUMNS,
                "No containers",
                actions=self._restart_button,
                color_of=_figure_color,
            )
        )
        self.controls = [H3Text("Container"), body]
        if charts:
            self.controls.append(self._chips)
            self.controls.append(
                ft.ResponsiveRow(
                    [ft.Container(_chart(c), col={"md": 6}) for c in charts],
                    spacing=Theme.Spacing.MD,
                    run_spacing=Theme.Spacing.MD,
                )
            )


async def restart(page: ft.Page, name: str) -> None:
    """Restart ``name`` through the restart API, and say how it went."""
    api = get_session_state(page).api_client
    result = await api.post(ui_runtime.RESTART_API.format(name=name))
    if isinstance(result, dict) and result.get("restarted") == name:
        SuccessSnackBar(ui_runtime.restart_done(name, bool(result.get("own")))).launch(
            page
        )
    else:
        ErrorSnackBar(f"Could not restart {name}").launch(page)


def _figure_color(row: dict[str, str], key: str) -> str | None:
    """A live figure past its threshold in its status's colour (``ui_runtime``
    sets ``<column>_status`` beside the figures it judges), as the htmx
    section's; under it, plain."""
    status = row.get(f"{key}_status")
    return get_status_color(status) if status in ("warning", "unhealthy") else None


def _chart(chart: dict[str, Any]) -> ft.Control:
    """The chart, or what it says with nothing in its window."""
    if chart["data"]["points"]:
        return LineChartCard.from_chart(
            chart["title"], chart["data"], chart["subtitle"]
        )
    return SecondaryText(f"{chart['title']}: {chart['empty']}")
