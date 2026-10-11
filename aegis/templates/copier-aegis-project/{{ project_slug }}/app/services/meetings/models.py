"""Meetings tables: a meeting the bot was asked to join, who was in it, and
what each of them said.

A participant is whoever the call names (a display name, and the
platform's own id when it gives one); linking one to a user ("this speaker
is me") is optional. Transcript times are seconds from the moment the bot
joined.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Index
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
