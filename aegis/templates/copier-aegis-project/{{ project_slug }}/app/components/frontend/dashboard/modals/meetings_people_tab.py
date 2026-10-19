"""Meetings > People in the Flet Overseer: how to work with each person who
speaks in the meetings, every owner's, beside a pane that reads the
selected guide (each point with the lines it rests on, then the
person's threads: ``meetings_threads``), keeps the owner's
note on them and writes the guide again, following it while it is being
written. The same as the htmx Overseer's People drawer, over the admin API
(``api/meetings/people.py``).
"""

from __future__ import annotations

from typing import Any

import flet as ft

from app.components.frontend.controls import DataTableColumn, PrimaryText
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.inputs import StyledTextField
from app.components.frontend.controls.record_detail import build_field_blocks
from app.components.frontend.controls.snack_bar import SuccessSnackBar
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_date

from .meetings_follow import ListBesidePane, WrittenPane, api, hint
from .meetings_threads import quote_lines, thread_controls
from .modal_sections import SectionHeader

API = "/api/v1/meetings/admin/people"


def guide_cells(row: dict[str, Any]) -> list[str]:
    """One guide's row (``GuideRow``): who, whose meetings, how many, when
    written."""
    guide = row["guide"]
    return [
        str(row.get("person") or ""),
        str(row.get("owner_user_id") or "-"),
        str(guide.get("meetings") or 0),
        format_date(guide.get("written_at")) or "-",
    ]


def _point(point: dict[str, Any]) -> ft.Control:
    """A point, the lines it rests on folded under it, each with where it
    was said."""
    text = PrimaryText(str(point.get("text") or ""), size=Theme.Typography.BODY)
    quotes = point.get("quotes") or []
    if not quotes:
        return text
    return ft.ExpansionTile(
        title=text,
        controls=quote_lines(quotes),
        dense=True,
    )


def guide_view(record: dict[str, Any]) -> ft.Column:
    """One person's guide read in full (``GuideRecord``): where it was read
    from, then each part with its points."""
    guide = record["guide"]
    meetings = int(guide.get("meetings") or 0)
    facts = [
        ("Owner", record.get("owner_user_id")),
        ("Read from", f"{meetings} meeting{'' if meetings == 1 else 's'}"),
        ("Written by", guide.get("model_name")),
    ]
    controls: list[ft.Control] = [
        PrimaryText(str(record.get("person") or ""), size=Theme.Typography.H3),
        *build_field_blocks([("", facts)]),
    ]
    if guide.get("error"):
        controls.append(
            PrimaryText(
                f"The last write failed: {guide['error']}",
                size=Theme.Typography.BODY,
                color=Theme.Colors.ERROR,
            )
        )
    if record.get("writing"):
        controls.append(hint("Writing the guide…"))
    for section in record.get("sections") or []:
        points = section.get("points") or []
        controls.append(SectionHeader(str(section.get("title") or "")))
        controls.extend([_point(p) for p in points] or [hint("Nothing yet.")])
    controls.extend(thread_controls(record.get("threads") or []))
    return ft.Column(
        controls, spacing=Theme.Spacing.SM, scroll=ft.ScrollMode.AUTO, expand=True
    )


class GuidePane(WrittenPane):
    """The selected guide, read from the API, with the owner's note and the
    guide written again, followed while it is being written."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__(page, API, "Select a person")

    def record_id(self, record: dict[str, Any]) -> int:
        return int(record["guide"]["id"])

    def draw(self, record: dict[str, Any]) -> None:
        guide_id = self.record_id(record)
        note = StyledTextField(
            label="Your note",
            value=record["guide"].get("note") or "",
            multiline=True,
            min_lines=2,
            max_lines=4,
        )
        buttons = [
            PulseButton(
                on_click_callable=lambda: self._save(guide_id, str(note.value or "")),
                text="Save the note",
                variant="muted",
                compact=True,
            )
        ]
        if record.get("can_write"):
            buttons.append(
                PulseButton(
                    on_click_callable=lambda: self.write_again(
                        guide_id, "guide", "This guide cannot be written now"
                    ),
                    text="Write it again",
                    variant="muted",
                    compact=True,
                )
            )
        self.content = ft.Column(
            [guide_view(record), note, ft.Row(buttons, spacing=8)],
            spacing=Theme.Spacing.MD,
            expand=True,
        )
        if self.page:
            self.update()

    async def _save(self, guide_id: int, note: str) -> None:
        record = await api(self.page).put(f"{API}/{guide_id}/note", json={"note": note})
        SuccessSnackBar("Note saved").launch(self.page)
        self.present(record)


class PeopleTab(ListBesidePane):
    """Every owner's guides, latest written first, beside the selected one."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__(
            page,
            API,
            GuidePane(page),
            columns=[
                DataTableColumn("Person", width=220, style="primary"),
                DataTableColumn("Owner", width=80, style="secondary"),
                DataTableColumn("Meetings", width=90, style="secondary"),
                DataTableColumn("Written", width=120, style="secondary"),
            ],
            cells=guide_cells,
            id_of=lambda row: int(row["guide"]["id"]),
            loading="Loading people...",
            empty="No guides yet: each person's is written after a meeting they speak in.",
        )
