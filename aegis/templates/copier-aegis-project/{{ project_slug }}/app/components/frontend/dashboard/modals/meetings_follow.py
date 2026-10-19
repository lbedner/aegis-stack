"""The Flet meetings modal's shared pieces: the API client and the small
hint text every tab uses, a record followed while something is happening
to it (the bot in a call, notes, a guide or a series being written): read
again every few seconds and drawn, while it is the one shown and its tab
is there (``SessionLoops``: Flet keeps a closed tab's session for an
hour), and a tab that lists records beside the pane that reads one."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    SecondaryText,
)
from app.components.frontend.controls.snack_bar import ErrorSnackBar
from app.components.frontend.core.session_health import (
    SessionLoops,
    page_is_connected,
)
from app.components.frontend.state.session_state import get_session_state
from app.components.frontend.theme import AegisTheme as Theme

from .modal_sections import EmptyStatePlaceholder

FOLLOW_SECONDS = 3


def api(page: ft.Page) -> Any:
    return get_session_state(page).api_client


def hint(text: str) -> ft.Control:
    return SecondaryText(text, size=Theme.Typography.BODY_SMALL)


async def follow(
    page: ft.Page,
    read: Callable[[], Awaitable[Any]],
    shown: Callable[[], bool],
    draw: Callable[[dict[str, Any]], None],
    busy: Callable[[dict[str, Any]], bool],
    seconds: float = FOLLOW_SECONDS,
) -> bool:
    """Whether it settled (its last read drawn); False once it is no longer
    shown, its tab is gone, or a read failed."""
    loops = SessionLoops(page, lambda: page_is_connected(page))
    while shown() and loops.alive():
        await asyncio.sleep(seconds)
        record = await read()
        if not isinstance(record, dict) or not shown():
            return False
        draw(record)
        if not busy(record):
            return True
    return False


class WrittenPane(ft.Container):
    """One record read from ``url`` (``url/<id>``) beside a list, written
    again from here and followed while it is being written (``writing``).
    A pane says which record it is (``record_id``) and draws it
    (``draw``)."""

    def __init__(self, page: ft.Page, url: str, placeholder: str) -> None:
        super().__init__()
        self.page = page
        self.url = url
        self._showing: int | None = None
        self.width = 560
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.border = ft.border.all(1, ft.Colors.OUTLINE_VARIANT)
        self.border_radius = Theme.Components.CARD_RADIUS
        self.content = EmptyStatePlaceholder(placeholder)

    def record_id(self, record: dict[str, Any]) -> int:
        raise NotImplementedError

    def draw(self, record: dict[str, Any]) -> None:
        raise NotImplementedError

    def will_unmount(self) -> None:
        """The modal closed: stop following."""
        self._showing = None

    async def show(self, record_id: int) -> None:
        self.present(await api(self.page).get(f"{self.url}/{record_id}"))

    def present(self, record: Any) -> None:
        if not isinstance(record, dict):
            return
        record_id = self.record_id(record)
        self._showing = record_id
        self.draw(record)
        if record.get("writing"):
            self.page.run_task(self._follow, record_id)

    async def _follow(self, record_id: int) -> None:
        await follow(
            self.page,
            lambda: api(self.page).get(f"{self.url}/{record_id}"),
            lambda: self._showing == record_id,
            self.draw,
            lambda record: bool(record.get("writing")),
        )

    async def write_again(self, record_id: int, action: str, refused: str) -> None:
        """Ask for it to be written again (``url/<id>/<action>``), then
        follow it; ``refused`` says so when it cannot be now."""
        record = await api(self.page).post(f"{self.url}/{record_id}/{action}")
        if record is None:
            ErrorSnackBar(refused).launch(self.page)
            return await self.show(record_id)
        self.present(record)


class ListBesidePane(ft.Container):
    """Every record ``url`` lists, a row each (``cells``), beside ``pane``,
    which reads the one clicked (its id: ``id_of``)."""

    def __init__(
        self,
        page: ft.Page,
        url: str,
        pane: WrittenPane,
        columns: list[DataTableColumn],
        cells: Callable[[dict[str, Any]], list[str]],
        id_of: Callable[[dict[str, Any]], int],
        loading: str,
        empty: str,
    ) -> None:
        super().__init__()
        self.page = page
        self._url, self._pane, self._columns = url, pane, columns
        self._cells, self._id_of, self._empty = cells, id_of, empty
        self._table = ft.Container(content=EmptyStatePlaceholder(loading), expand=True)
        self.content = ft.Row(
            [self._table, pane],
            spacing=Theme.Spacing.MD,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True
        page.run_task(self._load)

    async def _load(self) -> None:
        data = await api(self.page).get(self._url)
        rows = data if isinstance(data, list) else []
        self._table.content = DataTable(
            columns=self._columns,
            rows=[self._cells(r) for r in rows],
            scroll_height=600,
            empty_message=self._empty,
            on_row_click=lambda i: self.page.run_task(
                self._pane.show, self._id_of(rows[i])
            ),
        )
        # ``_load`` starts before the tab is mounted: update only once it is.
        if self._table.page:
            self._table.update()
