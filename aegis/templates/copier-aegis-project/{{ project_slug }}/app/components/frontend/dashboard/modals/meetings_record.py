"""One meeting read in full (the API's ``MeetingRecord``), as the meeting
pane shows it: a tab per part (its facts, its notes, what was asked of the
bot, its threads, what was said), its facts and each part of its notes in
a card of its own, each name in its color (``voices``)."""

from __future__ import annotations

from typing import Any

import flet as ft

from app.components.frontend.controls import PrimaryText, SecondaryText
from app.components.frontend.controls.tabs import OVERVIEW
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_clock

from .meetings_follow import PartTabs, card, details, hint, summary, voiced
from .meetings_moments import Acts, moments_controls
from .meetings_threads import ThreadsBlock

TRANSCRIPT = "Transcript"
# A transcript line's clock column, so every line starts at one edge.
CLOCK_WIDTH = 48


def following(record: dict[str, Any]) -> bool:
    """Read again every few seconds, while the service says something is
    happening (``MeetingRecord.following``)."""
    return bool(record.get("following"))


def has_threads(record: dict[str, Any]) -> bool:
    """Its threads are read once its notes are there and settled."""
    return bool(record.get("notes")) and not following(record)


def _items(
    items: list[dict[str, Any]], empty: str, voices: dict[str, int]
) -> list[ft.Control]:
    """Each item, after a dot in its owner's color."""
    if not items:
        return [hint(empty)]
    return [
        voiced(
            i.get("owner"),
            voices,
            PrimaryText(
                " · ".join(
                    str(part)
                    for part in (i.get("text"), i.get("owner"), i.get("due"))
                    if part
                ),
                size=Theme.Typography.BODY,
            ),
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
        voices = record.get("voices") or {}
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
            summary(str(notes.get("summary") or "")),
            card(
                "Yours",
                _items(
                    record.get("mine") or [],
                    "Nothing for you."
                    if me
                    else "Say which speaker you are to see yours.",
                    voices,
                ),
            ),
            card(
                "Action items",
                _items(notes.get("action_items") or [], "No action items.", voices),
            ),
            card(
                "Decisions",
                _items(notes.get("decisions") or [], "No decisions.", voices),
            ),
            card(
                "Open questions",
                _items(notes.get("open_questions") or [], "None left open.", voices),
            ),
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


def _transcript(
    lines: list[dict[str, Any]], hit: int | None, voices: dict[str, int]
) -> list[ft.Control]:
    """Each line: when, then who in their color, and what they said."""
    if not lines:
        return [hint("Nothing said yet.")]
    return [_line(line, hit, voices) for line in lines]


def _line(line: dict[str, Any], hit: int | None, voices: dict[str, int]) -> ft.Row:
    said = voiced(
        line.get("speaker"),
        voices,
        PrimaryText(
            f"{line.get('speaker')}: {line.get('text')}",
            size=Theme.Typography.BODY,
            # Each line a place to scroll to; a search's hit stands out.
            key=f"line-{line.get('id')}",
            weight=(
                ft.FontWeight.BOLD
                if hit and line.get("id") == hit
                else Theme.Typography.WEIGHT_REGULAR
            ),
        ),
    )
    # The width the clock leaves, so a long line wraps there.
    said.expand = True
    return ft.Row(
        [
            SecondaryText(
                format_clock(float(line.get("at") or 0)),
                size=Theme.Typography.BODY_SMALL,
                width=CLOCK_WIDTH,
            ),
            said,
        ],
        spacing=Theme.Spacing.SM,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )


class RecordView(PartTabs):
    """One meeting read in full, a tab per part; ``hit``, the line a search
    opened it at, marked. ``overview`` is what the pane adds under its
    facts (who I am, giving it away), ``selected`` the tab open first."""

    def __init__(
        self,
        record: dict[str, Any],
        hit: int | None = None,
        acts: Acts | None = None,
        *,
        overview: list[ft.Control] | None = None,
        selected: str = OVERVIEW,
    ) -> None:
        meeting = record["meeting"]
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
        voices = record.get("voices") or {}
        moments = moments_controls(record, *acts) if acts else []
        super().__init__(
            {
                OVERVIEW: [details(facts), *(overview or [])],
                "Notes": _notes(record),
                "Moments": moments or [hint("Nothing was asked of the bot.")],
                **(
                    {"Threads": [ThreadsBlock(int(meeting["id"]))]}
                    if has_threads(record)
                    else {}
                ),
                TRANSCRIPT: _transcript(record.get("transcript") or [], hit, voices),
            },
            selected=selected,
        )

    def open_at(self, line: int) -> None:
        """The transcript, scrolled to ``line``."""
        self.pick(TRANSCRIPT)
        if self.page:
            self.update()
            self.pages[TRANSCRIPT].scroll_to(key=f"line-{line}", duration=300)
