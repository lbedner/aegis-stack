"""What a call threw up that something can be done with
(``domains.moments``)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time import utcnow
from app.services.meetings.models.actions import ActionChoice, RunRecord


class MeetingMoment(SQLModel, table=True):
    """Something heard in a call that something can be done with: a
    question someone asked, first. One per line and kind, its text
    following the line as the caption grows (``domains.moments``)."""

    __tablename__ = "meeting_moment"
    __table_args__ = (UniqueConstraint("line_id", "kind"),)

    id: int | None = Field(default=None, primary_key=True)
    meeting_id: int = Field(foreign_key="meeting.id", ondelete="CASCADE", index=True)
    line_id: int = Field(foreign_key="meeting_transcript_line.id", ondelete="CASCADE")
    kind: str = Field(max_length=32)
    text: str = Field(sa_type=Text)
    topic: str | None = Field(
        default=None,
        sa_type=Text,
        description="What it is about, once the call is cleaned up: one card per topic",
    )
    created_at: datetime = Field(default_factory=utcnow)


class MomentRecord(BaseModel):
    """A moment as the API and both Overseers show it: what was heard, by
    whom, when in the call, what can be done with it and what has been."""

    id: int
    meeting_id: int
    line_id: int
    kind: str
    # What heads moments of its kind (``Questions``).
    title: str
    # What its card is about, once the call is cleaned up (``moments.clean``).
    topic: str | None = None
    text: str
    speaker: str
    at: float
    actions: list[ActionChoice] = []
    runs: list[RunRecord] = []
    # The moments of its kind said right after it, on the same thing
    # (``moments.service.GAP_SECONDS``): shown and asked of with it.
    also: list[MomentRecord] = []
