"""The Google accounts the bot joins as (``domains.accounts``)."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.core.time import utcnow


class BotAccount(SQLModel, table=True):
    """A Google account the bot joins calls as: an agent, to the people who
    use it. Each has its own name in the call and its own sign-in, kept as
    a secret (``login_secret``); the first is the default."""

    __tablename__ = "meeting_bot_account"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(
        max_length=40,
        unique=True,
        description="What it is picked by: meetings login --agent work",
    )
    display_name: str = Field(
        max_length=100, description="The name it joins as: its Google account's own"
    )
    email: str | None = Field(default=None, max_length=320)
    login_secret: str = Field(
        max_length=128, description="The secret its saved sign-in is kept under"
    )
    created_at: datetime = Field(default_factory=utcnow)
