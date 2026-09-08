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
