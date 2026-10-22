"""The actions taken on moments, and the tokens runners claim them with
(``domains.actions``)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import Text
from sqlmodel import Field, SQLModel

from app.core.time import utcnow
from app.services.meetings.models.base import _OWNER_FK

# Where a run stands: asked, claimed by what runs it, then done or failed.
ASKED, CLAIMED, DONE, FAILED = "asked", "claimed", "done", "failed"
# What claims a run of an action that runs in the app.
IN_THE_APP = "app"


class MeetingActionRun(SQLModel, table=True):
    """One action taken on a moment (``domains.actions``): asked, claimed
    by what runs it (the app, or a runner on another machine), then done
    or failed with what it came back with."""

    __tablename__ = "meeting_action_run"

    id: int | None = Field(default=None, primary_key=True)
    moment_id: int = Field(
        foreign_key="meeting_moment.id", ondelete="CASCADE", index=True
    )
    action: str = Field(max_length=64)
    prompt: str = Field(sa_type=Text)
    status: str = Field(default=ASKED, max_length=16, index=True)
    result: str | None = Field(default=None, sa_type=Text)
    runner: str | None = Field(default=None, max_length=255)
    asked_at: datetime = Field(default_factory=utcnow)
    claimed_at: datetime | None = None
    finished_at: datetime | None = None


class MeetingRunnerToken(SQLModel, table=True):
    """What a runner on another machine shows to claim an owner's runs and
    post their results. Only its digest is kept; the value is shown once."""

    __tablename__ = "meeting_runner_token"

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(
        default=None, foreign_key=_OWNER_FK, ondelete="CASCADE", index=True
    )
    name: str = Field(max_length=255)
    digest: str = Field(max_length=64, unique=True)
    hint: str = Field(max_length=16)
    created_at: datetime = Field(default_factory=utcnow)
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class ActionChoice(BaseModel):
    """An action a moment offers: its name, its button, and where it runs
    (``browser``, ``app`` or ``runner``)."""

    name: str
    label: str
    where: str
    # A browser action's prompt, to copy: it runs nowhere else.
    prompt: str | None = None


class RunRecord(BaseModel):
    """One action asked of a moment: where it stands, and what it came back
    with."""

    id: int
    action: str
    label: str
    status: str
    # Where it stands, as the pages say it (``Answered on laptop``).
    state: str
    result: str | None = None
    runner: str | None = None
    asked_at: datetime
    finished_at: datetime | None = None
