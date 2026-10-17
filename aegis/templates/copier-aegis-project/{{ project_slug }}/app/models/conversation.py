"""
SQLModel table definitions for AI conversation persistence.

These tables store conversation history in the project database.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel

from app.core.constants import ServiceName

# Whose tables these are (``ownership``): ``app/models`` is no part's folder.
PART_OF = ServiceName.AI


class Conversation(SQLModel, table=True):
    """
    Represents a conversation thread between a user and AI assistant.

    LLM information is tracked separately in llm_* tables.
    """

    __tablename__ = "conversation"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    title: str | None = Field(default=None, index=False)
    user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    meta_data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))

    # Relationship to messages
    messages: list["ConversationMessage"] = Relationship(back_populates="conversation")


class ConversationMessage(SQLModel, table=True):
    """
    Represents a single message within a conversation.

    Role can be 'user', 'assistant', or 'system'.
    """

    __tablename__ = "conversation_message"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    conversation_id: str = Field(foreign_key="conversation.id", index=True)
    role: str = Field(index=False)  # user, assistant, system
    content: str = Field(default="")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    meta_data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))

    # Relationship to conversation
    conversation: Conversation = Relationship(back_populates="messages")
