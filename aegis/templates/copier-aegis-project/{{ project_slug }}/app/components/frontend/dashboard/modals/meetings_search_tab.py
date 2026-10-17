"""Meetings > Search in the Flet Overseer: every owner's transcripts and
notes searched for the words typed, beside a pane that opens the meeting a
hit is in at its line. The same as the htmx Overseer's search box, over
the admin API (``api/meetings/search.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import flet as ft

from app.components.frontend.controls import DataTable, DataTableColumn
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.inputs import StyledTextField
from app.components.frontend.state.session_state import get_session_state
from app.components.frontend.theme import AegisTheme as Theme
from app.services.meetings.domains.people.service import said_when

from .modal_sections import EmptyStatePlaceholder

if TYPE_CHECKING:
    from .meetings_modal import MeetingPane

API = "/api/v1/meetings/admin/search"


def _api(page: ft.Page) -> Any:
    return get_session_state(page).api_client


def hit_cells(hit: dict[str, Any]) -> list[str]:
    """One hit's row (``SearchHit``): where it was said, who said it (or
    the part of the notes), and what."""
    at = hit.get("at")
    return [
        said_when(int(hit["meeting_id"]), None if at is None else float(at)),
        str(hit.get("speaker") or hit.get("part") or ""),
        str(hit.get("text") or ""),
    ]


class SearchTab(ft.Container):
    """The words, the hits for them newest meeting first, and the meeting
    the chosen hit is in, at its line."""

    def __init__(self, page: ft.Page, pane: MeetingPane) -> None:
        super().__init__()
        self.page = page
        self._pane = pane
        self._hits: list[dict[str, Any]] = []
        self._words = StyledTextField(
            compact=True,
            hint_text="A word said in any meeting or its notes",
            expand=True,
            on_submit=lambda _: self.page.run_task(self.search),
        )
        self._table = ft.Container(
            content=EmptyStatePlaceholder("Search what was said"), expand=True
        )
        toolbar = ft.Row(
            [
                self._words,
                PulseButton(on_click_callable=self.search, text="Search", compact=True),
            ],
            spacing=Theme.Spacing.SM,
        )
        self.content = ft.Row(
            [
                ft.Column(
                    [toolbar, self._table], spacing=Theme.Spacing.MD, expand=True
                ),
                pane,
            ],
            spacing=Theme.Spacing.MD,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True

    async def search(self) -> None:
        words = str(self._words.value or "").strip()
        if not words:
            return
        data = await _api(self.page).get(API, params={"q": words})
        self._hits = data if isinstance(data, list) else []
        self._table.content = DataTable(
            columns=[
                DataTableColumn("Where", width=150, style="secondary"),
                DataTableColumn("Who", width=120, style="primary"),
                DataTableColumn("Said", width=380),
            ],
            rows=[hit_cells(hit) for hit in self._hits],
            scroll_height=600,
            empty_message="Nothing said in any meeting has those words.",
            on_row_click=lambda i: self.page.run_task(self._open, i),
        )
        if self._table.page:
            self._table.update()

    async def _open(self, index: int) -> None:
        """The chosen hit's meeting, at its line."""
        hit = self._hits[index]
        line = hit.get("line_id")
        await self._pane.show(int(hit["meeting_id"]), line=int(line) if line else None)
