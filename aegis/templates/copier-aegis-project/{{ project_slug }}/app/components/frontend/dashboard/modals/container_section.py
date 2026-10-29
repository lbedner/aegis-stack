"""The Container section every component modal with a container behind it
gets (``BaseDetailPopup`` adds it): the same rows as the htmx Container section
(``ui_runtime.containers``), read again while the modal is open. Each row
has a Restart that confirms, then calls the restart API (behind
``get_admin_actor``; it audits every attempt), as the htmx section's does.
Where the dashboard may not make a change (``page_refusal``: the
address it was opened at), no Restart, and a line saying why. Given ``only_charts``, it is
those charts alone, with no table (a server's Overview)."""

import asyncio
from typing import Any

import flet as ft

from app.components.frontend.controls import ConfirmDialog, SecondaryText
from app.components.frontend.controls.record_detail import build_field_blocks
from app.components.frontend.controls.snack_bar import ErrorSnackBar, SuccessSnackBar
from app.components.frontend.core.changes import page_refusal
from app.components.frontend.core.session_health import SessionLoops, page_is_connected
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
# Each column's heading, ``ui_runtime`` row key and width (None fills).
# Fixed widths fit the default modal with the name and Restart beside them;
# the image, a long name of its own, is in what a row opens to (``DETAIL``).
COLUMNS = [
    ("Container", "name", None),
    ("State", "state", 90),
    (ui_runtime.FIGURES["cpu"], "cpu", 64),
    (ui_runtime.FIGURES["memory"], "memory", 150),
    (ui_runtime.FIGURES["network"], "network", 180),
    (ui_runtime.FIGURES["disk"], "disk", 190),
    ("Restarts", "restarts", 76),
    ("Up", "uptime", 50),
]
# What a row opens to: its image, and the figures its columns may cut short.
DETAIL = [
    ("Image", "image"),
    (ui_runtime.FIGURES["network"], "network"),
    (ui_runtime.FIGURES["disk"], "disk"),
]


class ContainerSection(ft.Column):
    """The containers behind one Overseer page (``page``: ``redis``, ...)."""

    def __init__(self, page: str, only_charts: tuple[str, ...] = ()) -> None:
        super().__init__(spacing=Theme.Spacing.SM)
        self._key = page
        self._only = only_charts
        # One table, its rows read again in place: a row the reader opened
        # stays open.
        self._table: TableTab | None = None
        self._open = False
        self._window = series.DEFAULT_WINDOW
        self._offered = series.WINDOWS
        self._chips = self._chips_for(self._offered)
        self._charts: list[dict[str, Any]] | None = None
        self._redraw = series.Redraw(self._window)
        self._show(ui_runtime.PENDING)

    def _chips_for(self, offered: tuple[tuple[int, str], ...]) -> DateRangeChips:
        """The range chips over ``offered`` (``ui_runtime.window_of``)."""
        return DateRangeChips(
            options=[(label, seconds) for seconds, label in offered],
            selected_days=self._window,
            on_change=lambda seconds: self.page.run_task(self.show_window, seconds),
        )

    async def show_window(self, seconds: int) -> None:
        """Chart the last ``seconds`` (a range chip)."""
        self._window = seconds
        self._redraw = series.Redraw(seconds)
        await self.load()

    def did_mount(self) -> None:
        self._open = True
        self.page.run_task(self._keep_reading)

    def will_unmount(self) -> None:
        self._open = False

    async def _keep_reading(self) -> None:
        """Re-read while the modal is open and its tab is there
        (``SessionLoops``: Flet keeps a closed tab's session for an hour)."""
        loops = SessionLoops(self.page, lambda: page_is_connected(self.page))
        while self._open and loops.alive():
            await self.load()
            await asyncio.sleep(REFRESH_SECONDS)

    async def load(self) -> None:
        """The cards, and the charts when they have new points (a long
        window's once its tier moves: ``series.Redraw``); the chips follow
        the windows the drawn charts offer."""
        self._window, offered = await ui_runtime.window_of(self._key, self._window)
        if offered != self._offered:
            self._offered, self._chips = offered, self._chips_for(offered)
        self._redraw.window = self._window
        draw = self._redraw.due()
        view, charts = await ui_runtime.section(
            self._key, self._window, draw=draw, only=self._only
        )
        self._charts = charts if charts is not None else self._charts
        self._show(view, self._charts)
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
        self.controls = [] if self._only else self._rows(view)
        if charts:
            self.controls.append(self._chips)
            self.controls.append(
                ft.ResponsiveRow(
                    [ft.Container(_chart(c), col={"md": 6}) for c in charts],
                    spacing=Theme.Spacing.MD,
                    run_spacing=Theme.Spacing.MD,
                )
            )

    def _rows(self, view: dict[str, Any]) -> list[ft.Control]:
        """The containers' table (or why there is none), and why there is
        no Restart where the API refuses it."""
        refused = page_refusal(self.page)
        if view["note"]:
            self._table = None
        elif self._table is None:
            self._table = TableTab(
                view["rows"],
                COLUMNS,
                "No containers",
                actions=None if refused else self._restart_button,
                color_of=_figure_color,
                detail=_detail,
            )
        else:
            self._table.show(view["rows"])
        shown: list[ft.Control] = [self._table or SecondaryText(view["note"])]
        if refused and view["rows"]:
            shown.append(SecondaryText(refused))
        return shown


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


def _detail(row: dict[str, str]) -> ft.Control:
    """A row's ``DETAIL``, label beside value."""
    fields = [(label, row.get(key)) for label, key in DETAIL]
    return ft.Column(build_field_blocks([("", fields)]), spacing=Theme.Spacing.XS)


def _chart(chart: dict[str, Any]) -> ft.Control:
    """The chart, or what it says with nothing in its window."""
    if chart["data"]["points"]:
        return LineChartCard.from_chart(
            chart["title"], chart["data"], chart["subtitle"]
        )
    return SecondaryText(f"{chart['title']}: {chart['empty']}")
