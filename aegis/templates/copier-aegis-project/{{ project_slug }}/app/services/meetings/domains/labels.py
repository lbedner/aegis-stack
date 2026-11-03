"""A meeting as the pages and the agent read it: its status, how long the
bot was in the call, its notes as points."""

from datetime import datetime
from typing import NamedTuple

from app.core.formatting import format_clock
from app.services.meetings.domains.notes.service import in_parts, whose
from app.services.meetings.models import Notes


def status_label(status: str) -> str:
    """A meeting's status as the pages say it: "in_call" -> "In call"."""
    return status.replace("_", " ").capitalize()


class NotePoint(NamedTuple):
    """One point of a meeting's notes as they read: its part ("Summary",
    "Action items"), whose it is and when it is due."""

    part: str
    text: str
    who: str | None
    due: str | None


def note_points(notes: Notes) -> list[NotePoint]:
    """The notes as they read: the summary, then each part's points."""
    return [
        NotePoint(
            status_label(kind), item.text, whose(item), getattr(item, "due", None)
        )
        for kind, items in in_parts(notes)
        for item in items
    ]


def call_length(joined: datetime | None, left: datetime | None) -> str | None:
    """How long the bot was in the call, as a stopwatch reads it; None
    until it has been in and out."""
    if joined is None or left is None:
        return None
    return format_clock((left - joined).total_seconds())
