"""What a live call can run on, as rows the app changes.

An engine is how the assistant uses a catalog model on a call, the way an
agent is how it uses one in chat: the model itself (its name, its maker,
its price) is the catalog's row (``llm_id``), and only what is the app's
lives here - its instructions and reply cap, and whether it is offered.
Every engine runs on the one call path (``voice/realtime_calls.py``). The defaults are seeded at startup when missing and never
overwrite an edit.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, Relationship, SQLModel

from app.core.time import utcnow
from app.services.ai.models.llm import LargeLanguageModel

# An engine's key, and a voice profile's pick of one.
KEY_LENGTH = 48


class LiveEngine(SQLModel, table=True):
    __tablename__ = "live_engine"

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(unique=True, index=True, max_length=KEY_LENGTH)
    llm_id: int = Field(foreign_key="large_language_model.id", index=True)
    # A line on what it is like; and what does not work yet, if anything.
    note: str = ""
    warning: str | None = None
    # Its own instructions: the live-call section ahead of the voice
    # agent's prompt.
    instructions: str | None = None
    # A hard cap on one spoken reply, where the engine takes one.
    max_output_tokens: int | None = Field(default=None, ge=1)
    is_enabled: bool = True
    sort_order: int = 0
    updated_at: datetime = Field(default_factory=utcnow)

    llm: LargeLanguageModel = Relationship()
