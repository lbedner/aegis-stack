"""Per-user agent memory model."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class AgentUserMemory(SQLModel, table=True):
    """
    One JSON memory document per user.

    Written by the built-in ``save_memory`` tool; ``memory`` holds
    ``structured_facts``: a list of ``{category, fact, saved_at}`` entries.
    Injected into chat context behind a prompt-injection guard block.
    """

    __tablename__ = "agent_user_memory"

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(unique=True, index=True)
    memory: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
