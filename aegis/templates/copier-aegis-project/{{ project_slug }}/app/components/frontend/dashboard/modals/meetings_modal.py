"""Meetings service detail modal: every owner's meetings beside a pane that
reads the selected one in full (its notes, transcript and how long each
speaker was heard), where the bot is asked to leave or the meeting is
deleted. The same reads and changes as the htmx Overseer's drawer, over
the admin API (``api/meetings/admin.py``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    ConfirmDialog,
    DataTable,
    DataTableColumn,
    PrimaryText,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.record_detail import build_field_blocks
from app.components.frontend.controls.snack_bar import SuccessSnackBar
from app.components.frontend.state.session_state import get_session_state
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_clock, format_date
from app.services.meetings.health import MEETINGS_MODAL_ID
from app.services.meetings.service import call_length, status_label
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ..cards.card_utils import get_status_detail
from .base_detail_popup import BaseDetailPopup
from .modal_sections import EmptyStatePlaceholder, SectionHeader

API = "/api/v1/meetings/admin"


def _api(page: ft.Page) -> Any:
    return get_session_state(page).api_client


def _when(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None


def meeting_cells(meeting: dict[str, Any]) -> list[str]:
    """One meeting's row: its link, owner, when asked, status and length."""
    length = call_length(_when(meeting.get("joined_at")), _when(meeting.get("left_at")))
    return [
        str(meeting.get("url") or "-"),
        str(meeting.get("owner_user_id") or "-"),
        format_date(meeting.get("created_at")) or "-",
        status_label(str(meeting.get("status") or "")),
        length or "-",
    ]


def actions_for(record: dict[str, Any]) -> list[str]:
    """What the admin can do to it now, as the service's read says
    (``MeetingRecord``): ask the bot to leave, delete it."""
    return [
        *(["leave"] if record.get("can_leave") else []),
        *(["delete"] if record.get("can_delete") else []),
    ]


def _items(items: list[dict[str, Any]], empty: str) -> list[ft.Control]:
    if not items:
        return [SecondaryText(empty, size=Theme.Typography.BODY_SMALL)]
    return [
        PrimaryText(
            " · ".join(
                str(part)
                for part in (i.get("text"), i.get("owner"), i.get("due"))
                if part
            ),
            size=Theme.Typography.BODY,
        )
        for i in items
    ]


def _notes(record: dict[str, Any]) -> list[ft.Control]:
    notes = record.get("notes")
    if notes:
        return [
            PrimaryText(str(notes.get("summary") or ""), size=Theme.Typography.BODY),
            SectionHeader("Action items"),
            *_items(notes.get("action_items") or [], "No action items."),
            SectionHeader("Decisions"),
            *_items(notes.get("decisions") or [], "No decisions."),
            SectionHeader("Open questions"),
            *_items(notes.get("open_questions") or [], "None left open."),
        ]
    if record.get("notes_error"):
        return [
            PrimaryText(
                f"The notes could not be written: {record['notes_error']}",
                size=Theme.Typography.BODY,
                color=Theme.Colors.ERROR,
            )
        ]
    return [SecondaryText("No notes.", size=Theme.Typography.BODY_SMALL)]


def _transcript(lines: list[dict[str, Any]]) -> list[ft.Control]:
    if not lines:
        return [SecondaryText("Nothing said yet.", size=Theme.Typography.BODY_SMALL)]
    return [
        PrimaryText(
            f"{format_clock(float(line.get('at') or 0))}  "
            f"{line.get('speaker')}: {line.get('text')}",
            size=Theme.Typography.BODY,
        )
        for line in lines
    ]


def record_view(record: dict[str, Any]) -> ft.Column:
    """One meeting read in full (``MeetingRecord``): who and how it went,
    its notes, then what was said."""
    meeting = record["meeting"]
    facts = [
        ("Status", record.get("status")),
        ("Length", record.get("length")),
        ("Bot", meeting.get("bot_name")),
        ("Owner", meeting.get("owner_user_id")),
        ("Owner speaks as", meeting.get("me")),
        ("Notes by", record.get("model_name")),
        ("Heard", record.get("heard")),
    ]
    return ft.Column(
        [
            PrimaryText(str(meeting.get("url") or ""), size=Theme.Typography.BODY),
            *build_field_blocks([("", facts)]),
            SectionHeader("Notes"),
            *_notes(record),
            SectionHeader("Transcript"),
            *_transcript(record.get("transcript") or []),
        ],
        spacing=Theme.Spacing.SM,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )


class MeetingPane(ft.Container):
    """The selected meeting, read from the API, with what can be done to it."""

    def __init__(self, page: ft.Page, on_change: Callable[[], Awaitable[None]]) -> None:
        super().__init__()
        self.page = page
        self._on_change = on_change
        self.width = 520
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.border = ft.border.all(1, ft.Colors.OUTLINE_VARIANT)
        self.border_radius = Theme.Components.CARD_RADIUS
        self.content = EmptyStatePlaceholder("Select a meeting")

    def clear(self) -> None:
        self.content = EmptyStatePlaceholder("Select a meeting")
        if self.page:
            self.update()

    async def show(self, meeting_id: int) -> None:
        record = await _api(self.page).get(f"{API}/{meeting_id}")
        if not isinstance(record, dict):
            return self.clear()
        buttons = {
            "leave": PulseButton(
                on_click_callable=lambda: self._leave(meeting_id),
                text="Ask it to leave",
                variant="amber",
                compact=True,
            ),
            "delete": PulseButton(
                on_click_callable=lambda: self._confirm_delete(meeting_id),
                text="Delete",
                variant="stop",
                compact=True,
            ),
        }
        self.content = ft.Column(
            [
                ft.Row([buttons[a] for a in actions_for(record)], spacing=8),
                record_view(record),
            ],
            spacing=Theme.Spacing.MD,
            expand=True,
        )
        if self.page:
            self.update()

    async def _leave(self, meeting_id: int) -> None:
        await _api(self.page).post(f"{API}/{meeting_id}/leave")
        SuccessSnackBar("Asked to leave").launch(self.page)
        await self._on_change()
        await self.show(meeting_id)

    async def _confirm_delete(self, meeting_id: int) -> None:
        async def _delete() -> None:
            await _api(self.page).delete(f"{API}/{meeting_id}")
            SuccessSnackBar("Meeting deleted").launch(self.page)
            self.clear()
            await self._on_change()

        ConfirmDialog(
            page=self.page,
            title=f"Delete meeting {meeting_id}?",
            message="Its transcript, notes and speakers go with it, for good.",
            confirm_text="Delete",
            destructive=True,
            on_confirm=_delete,
        ).show()


class MeetingsTab(ft.Container):
    """Every owner's meetings, newest first, beside the selected one."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        self._table = ft.Container(
            content=EmptyStatePlaceholder("Loading meetings..."), expand=True
        )
        self._pane = MeetingPane(page, on_change=self._load)
        self.content = ft.Row(
            [self._table, self._pane],
            spacing=Theme.Spacing.MD,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True
        page.run_task(self._load)

    async def _load(self) -> None:
        data = await _api(self.page).get(API)
        meetings = data if isinstance(data, list) else []
        self._table.content = DataTable(
            columns=[
                DataTableColumn("Meeting", width=300, style="primary"),
                DataTableColumn("Owner", width=80, style="secondary"),
                DataTableColumn("Requested", width=120, style="secondary"),
                DataTableColumn("Status", width=100),
                DataTableColumn("Length", width=80, style="secondary"),
            ],
            rows=[meeting_cells(m) for m in meetings],
            scroll_height=640,
            empty_message="No meetings yet",
            on_row_click=lambda i: self.page.run_task(
                self._pane.show, int(meetings[i]["id"])
            ),
        )
        # ``_load`` starts before the tab is mounted: update only once it is.
        if self._table.page:
            self._table.update()


class MeetingsDetailDialog(BaseDetailPopup):
    """Detail modal for the meetings service."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title(MEETINGS_MODAL_ID),
            subtitle_text=get_component_subtitle(
                MEETINGS_MODAL_ID, component_data.metadata
            ),
            sections=[MeetingsTab(page)],
            scrollable=False,
            width=1280,
            height=840,
            status_detail=get_status_detail(component_data),
        )
