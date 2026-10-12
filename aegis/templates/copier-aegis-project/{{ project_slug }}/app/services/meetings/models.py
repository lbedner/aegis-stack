"""Meetings tables: a meeting the bot was asked to join, who was in it, and
what each of them said.

A participant is whoever the call names (a display name, and the
platform's own id when it gives one); linking one to a user ("this speaker
is me") is optional. Transcript times are seconds from the moment the bot
joined. The notes are one model pass over the finished transcript (where
the stack has a model), each item citing the lines it came from.
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
    can_leave: bool
    can_delete: bool
