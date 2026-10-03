"""The Container section every component modal with a container behind it
gets (``BaseDetailPopup`` adds it): the same rows as the htmx Container section
(``ui_runtime.containers``), read again while the modal is open."""

import asyncio
from typing import Any

import flet as ft

from app.components.frontend.controls import H3Text, SecondaryText
from app.components.frontend.dashboard.modals.modal_sections import (
    DateRangeChips,
    LineChartCard,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core import series
from app.services.system import ui_runtime

from .table_tab import TableTab

REFRESH_SECONDS = 5.0
# Column widths in this modal; the columns are ``ui_runtime.COLUMNS``.
WIDTHS = {
    "state": 130,
    "cpu": 70,
    "memory": 150,
    "network": 170,
    "disk": 170,
    "restarts": 70,
    "uptime": 80,
    "image": 160,
}
COLUMNS = [(label, key, WIDTHS.get(key)) for key, label in ui_runtime.COLUMNS]


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
        view, charts = await asyncio.gather(
            ui_runtime.containers(self._key),
            ui_runtime.charts(self._key, self._window),
        )
        self._show(view, charts)
        if self.page is not None:
            self.update()

    def _show(
        self, view: dict[str, Any], charts: list[dict[str, Any]] | None = None
    ) -> None:
        body: ft.Control = (
            SecondaryText(view["note"])
            if view["note"]
            else TableTab(view["rows"], COLUMNS, "No containers")
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


def _chart(chart: dict[str, Any]) -> ft.Control:
    """The chart, or what it says with nothing in its window."""
    if chart["data"]["points"]:
        return LineChartCard.from_chart(
            chart["title"], chart["data"], chart["subtitle"]
        )
    return SecondaryText(f"{chart['title']}: {chart['empty']}")
