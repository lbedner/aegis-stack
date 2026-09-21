"""What the AI service speaks over the API and the CLI reads back."""

from __future__ import annotations

from pydantic import BaseModel


class ModelUsageStats(BaseModel):
    """Usage statistics for a single model."""

    model_id: str
    model_title: str
    vendor: str
    vendor_color: str
    requests: int
    tokens: int
    cost: float
    percentage: float


class RecentActivity(BaseModel):
    """A single recent usage activity entry."""

    timestamp: str
    model: str
    input_tokens: int
    output_tokens: int
    cost: float
    success: bool
    action: str

    # What the call cost in time and work. Optional throughout: a row
    # written before these columns existed, or by a path that does not
    # time itself, carries None - and the surface renders that as a
    # dash, never as a zero it did not measure.
    duration_ms: float | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    tool_calls: int | None = None
    user_id: str | None = None
    error_message: str | None = None


class UsageStatsResponse(BaseModel):
    """Aggregated LLM usage statistics response."""

    total_tokens: int
    input_tokens: int
    output_tokens: int
    total_cost: float
    total_requests: int
    success_rate: float
    models: list[ModelUsageStats]
    recent_activity: list[RecentActivity]
