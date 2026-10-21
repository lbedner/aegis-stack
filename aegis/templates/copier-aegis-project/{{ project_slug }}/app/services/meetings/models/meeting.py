"""A meeting the bot was asked to join, who was in it, and what each of
them said; and a meeting as the pages read it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import Index, Text
from sqlmodel import Field, SQLModel

from app.core.time import utcnow
from app.services.meetings.models.base import _OWNER_FK, MeetingStatus
from app.services.meetings.models.moments import MomentRecord
from app.services.meetings.models.notes import ActionItem, Notes


class Meeting(SQLModel, table=True):
    """One call the bot was asked to join, and how far it got."""

    __tablename__ = "meeting"
    # An owner's meetings, newest first, straight off the index.
    __table_args__ = (
        Index("ix_meeting_owner_created", "owner_user_id", "created_at", "id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(
        default=None,
        foreign_key=_OWNER_FK,
        ondelete="CASCADE",
        description="Who asked for the bot; NULL on a project without auth",
    )
    url: str = Field(max_length=2048)
    title: str | None = Field(
        default=None,
        sa_type=Text,
        description="What its calendar calls it, when its link is on one",
    )
    platform: str = Field(max_length=16)
    status: str = Field(default=MeetingStatus.REQUESTED, max_length=16)
    failure_reason: str | None = Field(
        default=None,
        max_length=500,
        description="Why it ended as failed: refused, timed out, the page changed",
    )
    bot_name: str = Field(max_length=100)
    account_id: int | None = Field(
        default=None,
        foreign_key="meeting_bot_account.id",
        description="The agent it was sent as",
    )
    created_at: datetime = Field(default_factory=utcnow)
    joined_at: datetime | None = None
    left_at: datetime | None = None
    seen_at: datetime | None = Field(
        default=None,
        description="The run's heartbeat: how a live run is told from a stopped one",
    )
    unattributed_seconds: float | None = Field(
        default=None,
        description="Seconds of audio the bot heard that no caption named",
    )


class MeetingParticipant(SQLModel, table=True):
    """A person as one call named them while the bot was in it."""

    __tablename__ = "meeting_participant"
    __table_args__ = (
        Index("ix_meeting_participant_meeting", "meeting_id"),
        Index("ix_meeting_participant_person", "person_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    meeting_id: int = Field(foreign_key="meeting.id", ondelete="CASCADE")
    person_id: int = Field(foreign_key="meeting_person.id")
    display_name: str = Field(max_length=255)
    heard_seconds: float | None = Field(
        default=None, description="Seconds of their audio the bot heard"
    )


class TranscriptLine(SQLModel, table=True):
    """One thing one participant said."""

    __tablename__ = "meeting_transcript_line"
    __table_args__ = (
        Index("ix_meeting_transcript_line_meeting", "meeting_id", "start_seconds"),
    )

    id: int | None = Field(default=None, primary_key=True)
    meeting_id: int = Field(foreign_key="meeting.id", ondelete="CASCADE")
    participant_id: int | None = Field(
        default=None, foreign_key="meeting_participant.id", ondelete="CASCADE"
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
    # Seconds heard of each speaker, by name; audio no caption named under
    # ``UNKNOWN``.
    heard_seconds: dict[str, float] = {}
    # Who spoke (the speakers "me" can be), the one the owner is, and the
    # action items that are theirs.
    people: list[str]
    me: str | None = None
    mine: list[ActionItem]
    under_way: bool
    writing: bool
    can_leave: bool
    can_delete: bool
    # A model to write notes with, and whether they can be written again now.
    can_write: bool
    can_rewrite: bool
    # What the call threw up (``domains.moments``).
    moments: list[MomentRecord] = []
    # Read it again every few seconds: the bot is in or on its way, the
    # notes are being written, or an action asked in the call is running.
    following: bool = False
