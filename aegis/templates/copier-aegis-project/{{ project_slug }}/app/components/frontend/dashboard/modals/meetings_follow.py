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
    PrimaryText,
    SecondaryText,
    SectionCard,
)
from app.components.frontend.controls.record_detail import build_field_blocks
from app.components.frontend.controls.snack_bar import ErrorSnackBar
from app.components.frontend.controls.tabs import OVERVIEW, PulseTabs, part_tab
from app.components.frontend.core.session_health import (
    SessionLoops,
    page_is_connected,
)
from app.components.frontend.state.session_state import get_session_state
from app.components.frontend.theme import AegisTheme as Theme

from .modal_sections import EmptyStatePlaceholder
from .modal_sections.chart_primitives import chart_dot

FOLLOW_SECONDS = 3


def api(page: ft.Page) -> Any:
    return get_session_state(page).api_client


def hint(text: str) -> ft.Control:
    return SecondaryText(text, size=Theme.Typography.BODY_SMALL)


def card(title: str, controls: list[ft.Control]) -> SectionCard:
    """One part of a record, in a card under its title."""
    return SectionCard(
        title,
        ft.Column(controls, spacing=Theme.Spacing.XS),
        body_padding=Theme.Spacing.MD,
    )


def summary(text: str) -> SectionCard:
    """A record's headline, in its Summary card."""
    return card("Summary", [PrimaryText(text, size=Theme.Typography.BODY)])


def details(facts: list[tuple[str, Any]]) -> SectionCard:
    """A record's facts, label beside value, in its Details card."""
    return card("Details", build_field_blocks([("", facts)]))


class PartTabs(PulseTabs):
    """A record's parts, a tab each (``parts``: its name, then what it
    shows), each scrolled on its own; ``selected`` the one open first. A
    pane drawing its record again opens the one ``picked`` (Flet keeps the
    reader's click in ``selected_index``)."""

    def __init__(
        self, parts: dict[str, list[ft.Control]], *, selected: str = OVERVIEW
    ) -> None:
        super().__init__(
            tabs=[part_tab(name, controls) for name, controls in parts.items()],
            selected_index=list(parts).index(selected) if selected in parts else 0,
        )
        # Each tab's page, by its name.
        self.pages = {tab.text: tab.content.content for tab in self.tabs}

    @property
    def picked(self) -> str:
        return list(self.pages)[self.selected_index]

    def pick(self, name: str) -> None:
        self.selected_index = list(self.pages).index(name)


def voiced(name: str | None, voices: dict[str, int], said: ft.Control) -> ft.Control:
    """``said`` after a dot in ``name``'s color in this meeting (the read's
    ``voices``), as the htmx pages mark a speaker; as it is with no name."""
    if not name:
        return said
    said.expand = True
    return ft.Row(
        [
            ft.Container(
                chart_dot(voices.get(name, 1), data="voice"),
                padding=ft.padding.only(top=6),
            ),
            said,
        ],
        spacing=6,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )


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
