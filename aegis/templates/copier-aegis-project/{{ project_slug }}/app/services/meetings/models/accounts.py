"""The Google accounts the bot joins as, and each one's picture
(``domains.accounts``)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import LargeBinary
from sqlmodel import Field, SQLModel

from app.core.time import utcnow
from app.services.meetings.models.base import _OWNER_FK


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
    default_owner_id: int | None = Field(
        default=None,
        foreign_key=_OWNER_FK,
        ondelete="SET NULL",
        description=(
            "Who owns a meeting it joins from its calendar when nobody on the"
            " invite has an account here; NULL: nobody"
        ),
    )
    created_at: datetime = Field(default_factory=utcnow)
    camera: bool = Field(
        default=True, description="Its camera on in a call, showing its card"
    )


class AgentImage(SQLModel, table=True):
    """An agent's picture, drawn on its card in a call (``bot.card``):
    kept apart from the agent, so a list of agents never carries it."""

    __tablename__ = "meeting_agent_image"

    account_id: int = Field(
        foreign_key="meeting_bot_account.id", primary_key=True, ondelete="CASCADE"
    )
    content_type: str = Field(max_length=32)
    data: bytes = Field(sa_type=LargeBinary)
    updated_at: datetime = Field(default_factory=utcnow)
