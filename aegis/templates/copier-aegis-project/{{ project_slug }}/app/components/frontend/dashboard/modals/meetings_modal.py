"""Meetings service detail modal: the bot sent to a call, and every owner's
meetings beside a pane that reads the selected one in full (my action
items once I say which speaker I am, the notes, the transcript, how long
each speaker was heard), following it while the bot is in or the notes
are being written, where the notes are written again, the bot asked to
leave or the meeting deleted. The same as the htmx Overseer's drawer, over
the owner's send route and the admin API (``api/meetings/admin.py``).
Search (``meetings_search_tab``) opens a hit's meeting in a pane of its
own, at its line.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from functools import partial
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    ConfirmDialog,
    DataTable,
    DataTableColumn,
    NativeDropdown,
    PrimaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.inputs import StyledTextField
from app.components.frontend.controls.record_detail import build_field_blocks
from app.components.frontend.controls.snack_bar import ErrorSnackBar, SuccessSnackBar
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_clock, format_date
from app.services.meetings.domains.accounts.service import agent_names
from app.services.meetings.health import MEETINGS_MODAL_ID
from app.services.meetings.service import call_length, status_label
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ..cards.card_utils import get_status_detail
from .base_detail_popup import BaseDetailPopup
from .meetings_agents_tab import AGENTS, AgentPicker, AgentsTab
from .meetings_calendar_tab import CalendarTab
from .meetings_follow import FOLLOW_SECONDS, api, follow, hint
from .meetings_moments import Acts, moment_actions, moments_controls
from .meetings_people_tab import PeopleTab
from .meetings_search_tab import SearchTab
from .meetings_series_tab import SeriesTab
from .meetings_threads import ThreadsBlock
from .modal_sections import EmptyStatePlaceholder, SectionHeader

API = "/api/v1/meetings/admin"
# Where a meeting is sent from: the owner's route, so the admin's own.
SEND = "/api/v1/meetings"


def _when(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None


def meeting_cells(
    meeting: dict[str, Any], agents: dict[int | None, str] | None = None
) -> list[str]:
    """One meeting's row: what its calendar calls it (else its link),
    owner, agent (by id, ``agents``), when asked, status and length."""
    length = call_length(_when(meeting.get("joined_at")), _when(meeting.get("left_at")))
    return [
        str(meeting.get("title") or meeting.get("url") or "-"),
        str(meeting.get("owner_user_id") or "-"),
        (agents or {}).get(meeting.get("account_id")) or "-",
        format_date(meeting.get("created_at")) or "-",
        status_label(str(meeting.get("status") or "")),
        length or "-",
    ]


def actions_for(record: dict[str, Any]) -> list[str]:
    """What the admin can do to it now, as the service's read says
    (``MeetingRecord``): ask the bot to leave, delete it, write the notes
    again, read the call over again for moments."""
    return [
        *(["leave"] if record.get("can_leave") else []),
        *(["delete"] if record.get("can_delete") else []),
        *(["rewrite"] if record.get("can_rewrite") else []),
        *(["look_over"] if record.get("can_look_over") else []),
    ]


def following(record: dict[str, Any]) -> bool:
    """Read again every few seconds, while the service says something is
    happening (``MeetingRecord.following``)."""
    return bool(record.get("following"))


def _items(items: list[dict[str, Any]], empty: str) -> list[ft.Control]:
    if not items:
        return [hint(empty)]
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
    if record.get("under_way"):
        return [hint("The notes are written once the bot has left.")]
    if record.get("writing"):
        return [hint("Writing the notes…")]
    if notes:
        me = record.get("me")
        failed = record.get("notes_error")
        return [
            *(
                [
                    PrimaryText(
                        "Writing them again failed, so these are the last ones: "
                        f"{failed}",
                        size=Theme.Typography.BODY_SMALL,
                        color=Theme.Colors.ERROR,
                    )
                ]
                if failed
                else []
            ),
            PrimaryText(str(notes.get("summary") or ""), size=Theme.Typography.BODY),
            SectionHeader("Yours"),
            *_items(
                record.get("mine") or [],
                "Nothing for you." if me else "Say which speaker you are to see yours.",
            ),
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
    return [
        hint(
            "No notes yet."
            if record.get("transcript")
            else "Nothing was said, so there is nothing to note."
        )
    ]


def has_threads(record: dict[str, Any]) -> bool:
    """Its threads are read once its notes are there and settled."""
    return bool(record.get("notes")) and not following(record)


def _transcript(lines: list[dict[str, Any]], hit: int | None) -> list[ft.Control]:
    if not lines:
        return [hint("Nothing said yet.")]
    return [
        PrimaryText(
            f"{format_clock(float(line.get('at') or 0))}  "
            f"{line.get('speaker')}: {line.get('text')}",
            size=Theme.Typography.BODY,
            # Each line a place to scroll to; a search's hit stands out.
            key=f"line-{line.get('id')}",
            weight=(
                ft.FontWeight.BOLD
                if hit and line.get("id") == hit
                else Theme.Typography.WEIGHT_REGULAR
            ),
        )
        for line in lines
    ]


def record_view(
    record: dict[str, Any], hit: int | None = None, acts: Acts | None = None
) -> ft.Column:
    """One meeting read in full (``MeetingRecord``): who and how it went,
    its notes, then what was said; ``hit``, the line a search opened it
    at, marked."""
    meeting = record["meeting"]
    name = str(meeting.get("title") or meeting.get("url") or "")
    facts = [
        ("Link", meeting.get("url") if meeting.get("title") else None),
        ("Status", record.get("status")),
        ("Length", record.get("length")),
        ("Bot", meeting.get("bot_name")),
        ("Owner", meeting.get("owner_user_id")),
        ("Owner speaks as", record.get("me")),
        ("Notes by", record.get("model_name")),
        ("Heard", record.get("heard")),
    ]
    return ft.Column(
        [
            PrimaryText(name, size=Theme.Typography.BODY),
            *build_field_blocks([("", facts)]),
            SectionHeader("Notes"),
            *_notes(record),
            *(moments_controls(record, *acts) if acts else []),
            *([ThreadsBlock(int(meeting["id"]))] if has_threads(record) else []),
            SectionHeader("Transcript"),
            *_transcript(record.get("transcript") or [], hit),
        ],
        spacing=Theme.Spacing.SM,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )


class MeetingPane(ft.Container):
    """The selected meeting, read from the API, with what can be done to it,
    followed while something is happening."""

    def __init__(self, page: ft.Page, on_change: Callable[[], Awaitable[None]]) -> None:
        super().__init__()
        self.page = page
        self._on_change = on_change
        self._showing: int | None = None
        self._following: int | None = None
        # The line a search opened the meeting at, and the view holding it.
        self._line: int | None = None
        self._view: ft.Column | None = None
        self.width = 520
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.border = ft.border.all(1, ft.Colors.OUTLINE_VARIANT)
        self.border_radius = Theme.Components.CARD_RADIUS
        self.content = EmptyStatePlaceholder("Select a meeting")

    def will_unmount(self) -> None:
        """The modal closed: stop following."""
        self._showing = None

    def clear(self) -> None:
        self._showing = None
        self.content = EmptyStatePlaceholder("Select a meeting")
        if self.page:
            self.update()

    async def show(self, meeting_id: int, line: int | None = None) -> None:
        """The meeting, scrolled to ``line`` (a search hit's) when given."""
        self._line = line
        self._present(await api(self.page).get(f"{API}/{meeting_id}"))
        if line and self._view is not None and self.page:
            self._view.scroll_to(key=f"line-{line}", duration=300)

    def _present(self, record: Any) -> None:
        """A meeting read in full (the API's ``MeetingRecord``, from a read
        or from the change that returned it), followed while something is
        happening."""
        if not isinstance(record, dict):
            return self.clear()
        meeting_id = int(record["meeting"]["id"])
        self._showing = meeting_id
        self._draw(record)
        if following(record) and self._following != meeting_id:
            self._following = meeting_id
            self.page.run_task(self._follow, meeting_id)

    async def _follow(self, meeting_id: int) -> None:
        """Read the meeting again while it is the one shown and something
        is still happening; then the list, once it settled."""
        try:
            if await follow(
                self.page,
                lambda: api(self.page).get(f"{API}/{meeting_id}"),
                lambda: self._showing == meeting_id,
                self._draw,
                following,
                FOLLOW_SECONDS,
            ):
                await self._on_change()
        finally:
            self._following = None

    def _draw(self, record: dict[str, Any]) -> None:
        meeting_id = int(record["meeting"]["id"])
        doing = {
            "leave": ("Ask it to leave", "amber", self._leave),
            "delete": ("Delete", "stop", self._confirm_delete),
            "rewrite": ("Write the notes again", "muted", self._rewrite),
            "look_over": ("Look over the call again", "muted", self._look_over),
        }
        buttons = {
            key: PulseButton(
                on_click_callable=partial(act, meeting_id),
                text=text,
                variant=variant,
                compact=True,
            )
            for key, (text, variant, act) in doing.items()
        }
        speaker = NativeDropdown(
            label="I am",
            value=record.get("me") or "",
            options=[
                ft.dropdown.Option(key="", text="Nobody here"),
                *[ft.dropdown.Option(key=name) for name in record.get("people") or []],
            ],
            width=220,
            enable_filter=False,
            enable_search=False,
            on_change=lambda e: self.page.run_task(
                self._set_me, meeting_id, str(e.control.value or "")
            ),
        )
        acts = moment_actions(
            self.page, f"{API}/{meeting_id}", lambda: self.show(meeting_id)
        )
        self._view = record_view(record, self._line, acts)
        self.content = ft.Column(
            [
                ft.Row([buttons[a] for a in actions_for(record)], spacing=8),
                *([speaker] if record.get("people") else []),
                self._view,
            ],
            spacing=Theme.Spacing.MD,
            expand=True,
        )
        if self.page:
            self.update()

    async def _set_me(self, meeting_id: int, name: str) -> None:
        """Which speaker the owner is (blank: nobody); the read it returns
        is drawn as it is."""
        record = await api(self.page).post(
            f"{API}/{meeting_id}/me", json={"name": name}
        )
        self._present(record)

    async def _rewrite(self, meeting_id: int) -> None:
        record = await api(self.page).post(f"{API}/{meeting_id}/notes")
        if record is None:
            ErrorSnackBar("No notes to write now").launch(self.page)
            return await self.show(meeting_id)
        self._present(record)

    async def _look_over(self, meeting_id: int) -> None:
        await api(self.page).post(f"{API}/{meeting_id}/moments/find")
        await self.show(meeting_id)

    async def _leave(self, meeting_id: int) -> None:
        await api(self.page).post(f"{API}/{meeting_id}/leave")
        SuccessSnackBar("Asked to leave").launch(self.page)
        await self._on_change()
        await self.show(meeting_id)

    async def _confirm_delete(self, meeting_id: int) -> None:
        async def _delete() -> None:
            await api(self.page).delete(f"{API}/{meeting_id}")
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
    """The bot sent to a call, and every owner's meetings, newest first,
    beside the selected one."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        self._link = StyledTextField(
            compact=True,
            hint_text="https://meet.google.com/abc-defg-hij",
            expand=True,
            on_submit=lambda _: self.page.run_task(self._send),
        )
        self._table = ft.Container(
            content=EmptyStatePlaceholder("Loading meetings..."), expand=True
        )
        self._pane = MeetingPane(page, on_change=self._load)
        self._agent = AgentPicker()
        toolbar = ft.Row(
            [
                self._link,
                self._agent,
                PulseButton(on_click_callable=self._send, text="Send", compact=True),
            ],
            spacing=Theme.Spacing.SM,
        )
        self.content = ft.Row(
            [
                ft.Column(
                    [toolbar, self._table], spacing=Theme.Spacing.MD, expand=True
                ),
                self._pane,
            ],
            spacing=Theme.Spacing.MD,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True
        page.run_task(self._load)

    async def _send(self) -> None:
        """Send the bot as the admin, then follow its meeting in the pane."""
        url = str(self._link.value or "").strip()
        if not url:
            return
        sent = await api(self.page).post(
            SEND, json={"url": url, **self._agent.chosen()}
        )
        if not isinstance(sent, dict):
            ErrorSnackBar("Not a meeting link the bot can join").launch(self.page)
            return
        self._link.value = ""
        if self._link.page:
            self._link.update()
        await self._load()
        await self._pane.show(int(sent["id"]))

    async def _load(self) -> None:
        data = await api(self.page).get(API)
        meetings = data if isinstance(data, list) else []
        listed = await api(self.page).get(AGENTS)
        agents = listed if isinstance(listed, list) else []
        self._agent.fill(agents)
        names = agent_names((a["account"]["id"], a["account"]["name"]) for a in agents)
        self._table.content = DataTable(
            columns=[
                DataTableColumn("Meeting", width=300, style="primary"),
                DataTableColumn("Owner", width=80, style="secondary"),
                DataTableColumn("Agent", width=100, style="secondary"),
                DataTableColumn("Requested", width=120, style="secondary"),
                DataTableColumn("Status", width=100),
                DataTableColumn("Length", width=80, style="secondary"),
            ],
            rows=[meeting_cells(m, names) for m in meetings],
            scroll_height=600,
            empty_message="No meetings yet",
            on_row_click=lambda i: self.page.run_task(
                self._pane.show, int(meetings[i]["id"])
            ),
        )
        # ``_load`` starts before the tab is mounted: update only once it is.
        if self._table.page:
            self._table.update()


def _search_tab(page: ft.Page) -> SearchTab:
    """Search, its hits opening in a pane of its own; a change made there
    (a meeting deleted) searches again."""
    tab: SearchTab = SearchTab(page, MeetingPane(page, on_change=lambda: tab.search()))
    return tab


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
            sections=[
                PulseTabs(
                    selected_index=0,
                    expand=True,
                    tabs=[
                        ft.Tab(text="Meetings", content=MeetingsTab(page)),
                        ft.Tab(text="Calendar", content=CalendarTab(page)),
                        ft.Tab(text="Search", content=_search_tab(page)),
                        ft.Tab(text="Series", content=SeriesTab(page)),
                        ft.Tab(text="People", content=PeopleTab(page)),
                        ft.Tab(text="Agents", content=AgentsTab(page)),
                    ],
                )
            ],
            scrollable=False,
            width=1280,
            height=840,
            status_detail=get_status_detail(component_data),
        )
