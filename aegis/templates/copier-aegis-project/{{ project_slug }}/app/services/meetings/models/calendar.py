"""What is on each agent's calendar (``domains.calendar``)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column, Index, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class CalendarEvent(SQLModel, table=True):
    """One time a meeting on an agent's calendar happens, as the calendar
    last said (``domains.calendar``): kept so the agent is sent on time and
    the calendar is drawn without reading every feed. ``key`` is the event's
    UID and the time it was first set for; ``meeting_id`` is the call the
    agent was sent into, while that meeting is kept."""

    __tablename__ = "meeting_calendar_event"
    __table_args__ = (
        UniqueConstraint("account_id", "key"),
        # What is on, in a window of time, straight off the index.
        Index("ix_meeting_calendar_event_starts", "starts_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(
        foreign_key="meeting_bot_account.id",
        ondelete="CASCADE",
        description="The agent whose calendar it is on",
    )
    key: str = Field(max_length=1024)
    title: str = Field(default="", sa_type=Text)
    starts_at: datetime
    ends_at: datetime
    url: str | None = Field(default=None, max_length=2048)
    organizer: str | None = Field(default=None, max_length=320)
    emails: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description="Every email on the invite, the organizer's first",
    )
    cancelled: bool = False
    meeting_id: int | None = Field(
        default=None, foreign_key="meeting.id", ondelete="SET NULL"
    )
    sent_at: datetime | None = Field(
        default=None,
        description="When the agent was sent in: once, even if that meeting is deleted",
    )
