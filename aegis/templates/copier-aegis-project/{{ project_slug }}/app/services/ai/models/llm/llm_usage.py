"""LLM Usage model for tracking AI interactions."""

from datetime import UTC, datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


class LLMUsage(SQLModel, table=True):
    """
    Records every LLM call with token usage and calculated costs.

    Uses model_id string (e.g., "openai/gpt-4") instead of FK to decouple
    usage tracking from catalog lifecycle. Joins can be done on model_id.

    The action field accepts any string value for flexibility -
    callers can define their own action types (e.g., "chat", "stream_chat",
    "completion", etc.).
    """

    __tablename__ = "llm_usage"
    __table_args__ = (
        # Compound index for efficient time-range + model aggregation queries
        Index("ix_llm_usage_timestamp_model_id", "timestamp", "model_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    model_id: str = Field(index=True)
    user_id: str | None = Field(default=None, index=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_cost: float = Field(ge=0)
    success: bool = Field(default=True)
    error_message: str | None = None
    action: str = Field(index=True)

    # What the call cost in time and work. All nullable, and deliberately
    # not defaulted to zero: "nobody measured this" and "this was zero"
    # are different facts, and a backfilled zero becomes a lie the moment
    # anything averages the column. A path that does not time itself
    # records None; a turn that genuinely used no tools records 0.
    duration_ms: float | None = Field(default=None, ge=0)
    cache_read_tokens: int | None = Field(default=None, ge=0)
    cache_write_tokens: int | None = Field(default=None, ge=0)
    tool_calls: int | None = Field(default=None, ge=0)
