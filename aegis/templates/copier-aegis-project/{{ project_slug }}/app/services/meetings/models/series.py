"""A series of meetings on one link and what it keeps coming back to
(``domains.series``)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from pydantic import Field as Described
from sqlalchemy import Index, Text
from sqlmodel import Field, SQLModel

from app.core.time import utcnow
from app.services.meetings.models.base import _OWNER_FK
from app.services.meetings.models.notes import NoteItem
from app.services.meetings.models.people import ThreadSection


class Theme(NoteItem):
    """Something a series of meetings keeps coming back to: an ask made
    again, a blocker that keeps returning, a worry nobody resolves, with
    every line it was said in (across the meetings)."""

    status: Literal["open", "answered", "done"] = Described(
        default="open",
        description="Answered or done by the latest meeting, else still open",
    )


class SeriesNotes(BaseModel):
    """What a series of meetings said over time, as the model writes it:
    a headline, what it keeps coming back to, and the run told a short
    point at a time, each citing the lines it rests on."""

    summary: str = Described(
        description="One sentence, at most 25 words: where the series stands now"
    )
    themes: list[Theme] = Described(
        default_factory=list,
        description=(
            "Each thing raised in more than one meeting, citing every line it"
            " was said in"
        ),
    )
    settled: list[NoteItem] = Described(
        default_factory=list,
        description="At most 5 things decided or done, a few words each",
    )
    shifted: list[NoteItem] = Described(
        default_factory=list,
        description=(
            "At most 5 positions or priorities that changed, a few words each"
            " as 'from → to'"
        ),
    )
    still_open: list[NoteItem] = Described(
        default_factory=list,
        description="At most 5 things still unresolved, a few words each",
    )
    mood: list[NoteItem] = Described(
        default_factory=list,
        description="How the room feels about the work, a few words each",
    )


# What the run is told in (``SeriesNotes``' parts past the themes), with
# its heading: one card each.
OVER_TIME = {
    "settled": "Settled",
    "shifted": "Shifted",
    "still_open": "Still open",
    "mood": "Mood",
}


class MeetingSeries(SQLModel, table=True):
    """An owner's meetings on one link: a recurring meeting keeps its link
    every time (``domains.series``). What they said over time and what
    they keep coming back to (``MeetingTheme``), one model pass over their
    notes, written again as each meeting joins it; or why the last pass
    could not be."""

    __tablename__ = "meeting_series"
    __table_args__ = (Index("ix_meeting_series_link", "link"),)

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(
        default=None,
        foreign_key=_OWNER_FK,
        ondelete="CASCADE",
        description="Whose meetings they are; NULL on a project without auth",
    )
    link: str = Field(
        max_length=2048, description="The meeting link without what follows it"
    )
    name: str = Field(
        default="", max_length=255, description="Its calendar event's title, if any"
    )
    summary: str = Field(default="", sa_type=Text)
    meetings: int = Field(default=0, description="How many meetings it was read from")
    error: str | None = Field(default=None, max_length=500)
    model_name: str | None = Field(default=None, max_length=255)
    written_at: datetime = Field(default_factory=utcnow)


class MeetingTheme(SQLModel, table=True):
    """One point of a series, in its part (``kind``: a theme, or one of
    ``OVER_TIME``) and place."""

    __tablename__ = "meeting_theme"
    __table_args__ = (Index("ix_meeting_theme_series", "series_id", "ord"),)

    id: int | None = Field(default=None, primary_key=True)
    series_id: int = Field(foreign_key="meeting_series.id", ondelete="CASCADE")
    kind: str = Field(default="themes", max_length=32)
    ord: int
    text: str = Field(sa_type=Text)
    status: str = Field(default="open", max_length=16)


class MeetingThemeLine(SQLModel, table=True):
    """A transcript line a theme was said in, in order."""

    __tablename__ = "meeting_theme_line"
    __table_args__ = (Index("ix_meeting_theme_line_line", "line_id"),)

    theme_id: int = Field(
        foreign_key="meeting_theme.id", primary_key=True, ondelete="CASCADE"
    )
    line_id: int = Field(
        foreign_key="meeting_transcript_line.id", primary_key=True, ondelete="CASCADE"
    )
    ord: int


class SeriesRow(BaseModel):
    """A series with what it is called: its calendar event's title, else
    its link (``SeriesService.list``)."""

    series: MeetingSeries
    name: str


class SeriesRecord(SeriesRow):
    """One series read in full (``SeriesService.read``): its meetings,
    newest first; its run over time, a section per card that has points
    (``over_time``); what it keeps coming back to, as a thread section; and
    whether it can be written again now."""

    meetings: list[int]
    over_time: list[ThreadSection] = []
    sections: list[ThreadSection]
    writing: bool
    can_write: bool
