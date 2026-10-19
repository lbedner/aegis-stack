"""Commitments, contradictions and positions in the Flet Overseer: a
meeting's (loaded into its pane once its notes are there) and a person's
(read with their guide), drawn from the API's sections
(``ThreadSection``). The same as the htmx Overseer's ``_threads.html``."""

from __future__ import annotations

from typing import Any

import flet as ft

from app.components.frontend.controls import PrimaryText
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import counted
from app.services.meetings.domains.people.service import said_when

from .meetings_follow import api, hint
from .modal_sections import SectionHeader

API = "/api/v1/meetings/admin"


def quote_lines(quotes: list[dict[str, Any]]) -> list[ft.Control]:
    return [
        hint(
            f"{q.get('speaker')}: {q.get('text')}  "
            f"{said_when(int(q['meeting_id']), float(q.get('at') or 0))}"
        )
        for q in quotes
    ]


def _item(item: dict[str, Any], other: str | None) -> ft.Control:
    """One thread: whose, what, where it stands, then its lines folded
    under it, and its other lines under ``other``."""
    said = " · ".join(
        str(part)
        for part in (
            item.get("speaker"),
            item.get("text"),
            item.get("detail"),
            str(item.get("status") or "").capitalize(),
        )
        if part
    )
    quotes = item.get("quotes") or []
    others = item.get("other") or []
    count = len(quotes) + len(others)
    lines = ft.ExpansionTile(
        title=hint(counted(count, "line")),
        controls=[
            *quote_lines(quotes),
            *([hint(other or ""), *quote_lines(others)] if others else []),
        ],
        dense=True,
    )
    return ft.Column([PrimaryText(said, size=Theme.Typography.BODY), lines], spacing=0)


def thread_controls(sections: list[dict[str, Any]]) -> list[ft.Control]:
    """Each section under its heading, its threads or why there are none."""
    controls: list[ft.Control] = []
    for section in sections:
        items = section.get("items") or []
        controls.append(SectionHeader(str(section.get("title") or "")))
        controls.extend(
            [_item(i, section.get("other")) for i in items]
            or [hint(str(section.get("empty") or ""))]
        )
    return controls


class ThreadsBlock(ft.Column):
    """A meeting's threads, read from the admin API once it is shown."""

    def __init__(self, meeting_id: int) -> None:
        super().__init__(spacing=Theme.Spacing.SM)
        self._meeting_id = meeting_id

    def did_mount(self) -> None:
        self.page.run_task(self._load)

    async def _load(self) -> None:
        sections = await api(self.page).get(f"{API}/{self._meeting_id}/threads")
        self.controls = thread_controls(sections if isinstance(sections, list) else [])
        if self.page:
            self.update()
