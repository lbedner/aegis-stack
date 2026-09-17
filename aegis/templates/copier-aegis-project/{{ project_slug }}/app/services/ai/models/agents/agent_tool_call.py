"""Per-tool-call ledger model."""

from datetime import datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from app.core.time import utcnow


class AgentToolCall(SQLModel, table=True):
    """One tool call made by a chat agent.

    ``llm_usage`` is the turn-level ledger: model, tokens, cost, duration.
    It cannot say which tool ran inside the turn, which tools get reached
    for together, or how often a turn spends its entire call budget and
    still answers short. An agent with a handful of tools does not need
    this; an agent with twenty cannot be reasoned about without it.

    Rows group by ``turn_id``. A turn that used its whole budget is
    ``max(call_index) + 1 == the agent's tool-call limit``, derived when
    you ask rather than flagged when writing, so nothing has to know the
    limit at write time.

    Telemetry, not billing: writes are best-effort and never fail a turn.
    """

    __tablename__ = "agent_tool_call"
    __table_args__ = (
        # The debrief reads one tool over a window; the turn index groups
        # a turn back together.
        Index("ix_agent_tool_call_name_created", "tool_name", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    turn_id: str = Field(max_length=32, index=True)
    tool_name: str = Field(max_length=64)
    # Position within the turn, 0-based. Ceiling hits derive from it.
    call_index: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    # How much context the result cost: the other half of "is this tool
    # worth its slot".
    result_bytes: int = Field(default=0, ge=0)
    ok: bool = Field(default=True)
    error: str | None = Field(default=None, max_length=500)
    user_id: str | None = Field(default=None, index=True)
    agent_slug: str | None = Field(default=None, index=True)
    conversation_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
