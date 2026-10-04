"""A card the assistant drew in a reply, with its data frozen into it.

A card is an answer given at a time: re-resolving its rows at render time
would quietly rewrite it, so the chart drawn on Tuesday would show
Thursday's numbers beside Tuesday's sentence. The payload is stored as
the assistant computed it, shaped by its kind's schema (``domains/chat/cards.py``).

Addressed by id, never by payload: the stored trace clips tool results at
2 KB, so the message carries only a marker ``{"kind": "chat_card", "id"}``.
"""

from datetime import datetime
from typing import Any
import uuid

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.core.time import utcnow


class ChatCard(SQLModel, table=True):
    __tablename__ = "chat_card"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex, primary_key=True, max_length=32
    )
    # The scope: a card is shown only in the conversation that drew it.
    conversation_id: str = Field(index=True, max_length=64)
    kind: str = Field(max_length=32)
    payload: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=utcnow)
