"""Meetings tables: a meeting the bot was asked to join, who was in it, and
what each of them said.

A participant is whoever the call names (a display name, and the
platform's own id when it gives one); linking one to a user ("this speaker
is me") is optional. Transcript times are seconds from the moment the bot
joined. The notes are one model pass over the finished transcript (where
the stack has a model), each item citing the lines it came from; so is
each person's guide, how to work with them, read across the owner's
meetings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel
from pydantic import Field as Described
from sqlalchemy import JSON, Column, Index
from sqlmodel import Field, SQLModel

from app.core.time import utcnow


class Platform(StrEnum):
    MEET = "meet"
    TEAMS = "teams"
    ZOOM = "zoom"


class MeetingStatus(StrEnum):
    REQUESTED = "requested"
    JOINING = "joining"
    WAITING = "waiting"  # in the lobby, waiting to be admitted
    IN_CALL = "in_call"
    LEAVING = "leaving"  # asked to leave; the bot goes on its next look
    LEFT = "left"
    FAILED = "failed"


class Meeting(SQLModel, table=True):
    """One call the bot was asked to join, and how far it got."""

    __tablename__ = "meeting"
    # An owner's meetings, newest first, straight off the index.
    __table_args__ = (
        Index("ix_meeting_owner_created", "owner_user_id", "created_at", "id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    # Who asked for the bot; NULL on a project without auth.
    owner_user_id: int | None = Field(default=None)
    url: str = Field(max_length=2048)
    platform: str = Field(max_length=16)
    status: str = Field(default=MeetingStatus.REQUESTED, max_length=16)
    # Why it ended as ``failed``: refused, timed out, the page changed.
    failure_reason: str | None = Field(default=None, max_length=500)
    bot_name: str = Field(max_length=100)
    created_at: datetime = Field(default_factory=utcnow)
    joined_at: datetime | None = None
    left_at: datetime | None = None
    # The run's heartbeat: how ``fail_interrupted`` tells a live run from a
    # stopped one.
    seen_at: datetime | None = None
    # The speaker the owner is, by display name: whose action items are
    # "mine". Carried from the owner's last meeting (``remember_me``).
    me: str | None = Field(default=None, max_length=255)
    # Seconds of audio the bot heard from each speaker (``audio.Hearing``),
    # kept once it is out of the call.
    heard: dict[str, float] | None = Field(default=None, sa_column=Column(JSON))


class MeetingParticipant(SQLModel, table=True):
    """Someone the call named while the bot was in it."""

    __tablename__ = "meeting_participant"
    __table_args__ = (Index("ix_meeting_participant_meeting", "meeting_id"),)

    id: int | None = Field(default=None, primary_key=True)
    meeting_id: int = Field(foreign_key="meeting.id")
    display_name: str = Field(max_length=255)
    platform_id: str | None = Field(default=None, max_length=255)
    # The user this speaker is, when someone says so.
    user_id: int | None = Field(default=None)


class TranscriptLine(SQLModel, table=True):
    """One thing one participant said."""

    __tablename__ = "meeting_transcript_line"
    __table_args__ = (
        Index("ix_meeting_transcript_line_meeting", "meeting_id", "start_seconds"),
    )

    id: int | None = Field(default=None, primary_key=True)
    meeting_id: int = Field(foreign_key="meeting.id")
    participant_id: int | None = Field(
        default=None, foreign_key="meeting_participant.id"
    )
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True)
class Caption:
    """One caption block as the call shows it now. ``line`` stays the same
    while the speaker's block grows, so it names the transcript line."""

    line: str
    speaker: str
    text: str


class NoteItem(BaseModel):
    text: str
    lines: list[int] = Described(
        default_factory=list, description="Ids of the transcript lines it came from"
    )


class ActionItem(NoteItem):
    owner: str | None = Described(
        default=None,
        description="The speaker who has to do it, named as in the transcript",
    )
    due: str | None = Described(default=None, description="When, if it was said")


class Notes(BaseModel):
    """What a meeting came to, as the model writes it."""

    summary: str
    decisions: list[NoteItem] = []
    action_items: list[ActionItem] = []
    open_questions: list[NoteItem] = []

    def mine(self, me: str | None) -> list[ActionItem]:
        """The action items ``me`` (a speaker's name) has to do."""
        return [a for a in self.action_items if me and a.owner == me]


class MeetingNotes(SQLModel, table=True):
    """A meeting's notes, or why the model could not write them. Written
    again in place (a better model, a fixed transcript)."""

    __tablename__ = "meeting_notes"

    meeting_id: int = Field(foreign_key="meeting.id", primary_key=True)
    content: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    error: str | None = Field(default=None, max_length=500)
    model_name: str | None = Field(default=None, max_length=255)
    written_at: datetime = Field(default_factory=utcnow)

    def notes(self) -> Notes | None:
        return None if self.content is None else Notes.model_validate(self.content)


class Guide(BaseModel):
    """How to work with one person, as the model reads it from what they
    said across the owner's meetings: only how they work, each point citing
    the lines it rests on."""

    cares_about: list[NoteItem] = Described(
        default_factory=list, description="What they keep coming back to"
    )
    information: list[NoteItem] = Described(
        default_factory=list,
        description=(
            "How they like their information: big picture or detail, a demo "
            "or numbers, short or thorough"
        ),
    )
    decides: list[NoteItem] = Described(
        default_factory=list,
        description=(
            "How they decide and commit: a quick yes, needs to see it first, "
            "defers to someone, says they will and does or does not"
        ),
    )
    lands: list[NoteItem] = Described(
        default_factory=list,
        description="What lands with them and what gets pushback",
    )

    def points(self) -> list[NoteItem]:
        """Every point, part by part."""
        return [item for key in GUIDE_SECTIONS for item in getattr(self, key)]


# Each part of a guide, in the order the pages show them, with its heading.
GUIDE_SECTIONS = {
    "cares_about": "What they care about",
    "information": "How they like their information",
    "decides": "How they decide and commit",
    "lands": "What lands with them",
}


class PersonGuide(SQLModel, table=True):
    """How to work with one person who speaks in an owner's meetings, or
    why the model could not write it. Written again as meetings accrue; the
    owner's own note on them is kept across every rewrite."""

    __tablename__ = "meeting_person_guide"
    __table_args__ = (
        Index("ix_meeting_person_guide_owner_person", "owner_user_id", "person"),
    )

    id: int | None = Field(default=None, primary_key=True)
    # Whose meetings it is read from; NULL on a project without auth.
    owner_user_id: int | None = Field(default=None)
    # The speaker, by display name, as the calls name them.
    person: str = Field(max_length=255)
    content: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    error: str | None = Field(default=None, max_length=500)
    model_name: str | None = Field(default=None, max_length=255)
    # How many meetings it was read from.
    meetings: int = 0
    note: str | None = Field(default=None, max_length=2000)
    written_at: datetime = Field(default_factory=utcnow)

    def guide(self) -> Guide | None:
        return None if self.content is None else Guide.model_validate(self.content)


class Quote(BaseModel):
    """A transcript line a guide's point rests on."""

    id: int
    meeting_id: int
    speaker: str
    at: float
    text: str


class GuidePoint(BaseModel):
    text: str
    quotes: list[Quote]


class GuideSection(BaseModel):
    key: str
    title: str
    points: list[GuidePoint]


class GuideRecord(BaseModel):
    """One person's guide read in full (``PeopleService.read``): each part
    with the lines its points rest on, and whether it can be written again
    now."""

    guide: PersonGuide
    sections: list[GuideSection]
    writing: bool
    can_write: bool


class TranscriptRow(BaseModel):
    """One transcript line as the pages and the API show it."""

    id: int
    speaker: str
    at: float
    text: str


class MeetingRecord(BaseModel):
    """One meeting read in full (``MeetingsService.read``): what both
    Overseers and the API show of it, and what can be done to it now."""

    meeting: Meeting
    notes: Notes | None
    notes_error: str | None
    model_name: str | None
    transcript: list[TranscriptRow]
    status: str
    length: str | None
    heard: str | None
    # Who spoke (the speakers "me" can be), and the action items of the one
    # the owner is.
    people: list[str]
    mine: list[ActionItem]
    under_way: bool
    writing: bool
    can_leave: bool
    can_delete: bool
    # A model to write notes with, and whether they can be written again now.
    can_write: bool
    can_rewrite: bool
