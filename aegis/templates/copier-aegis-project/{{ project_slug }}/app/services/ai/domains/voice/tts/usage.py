"""
TTS usage tracking model.

Tracks Text-to-Speech synthesis calls for analytics and billing.
"""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel


class TTSUsage(SQLModel, table=True):
    """Track TTS usage for analytics and billing.

    Records each TTS synthesis call with relevant metrics for
    cost tracking, performance analysis, and usage monitoring.
    """

    __tablename__ = "tts_usage"

    id: int | None = SQLField(default=None, primary_key=True)

    # Provider and model information
    provider: str = SQLField(index=True)  # "openai", etc.
    model: str | None = None  # "tts-1", "tts-1-hd", etc.
    voice: str | None = None  # Voice ID used

    # Who/when
    user_id: str | None = SQLField(default=None, index=True)
    timestamp: datetime = SQLField(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), index=True),
    )

    # Input metrics
    input_characters: int | None = None  # Text length for synthesis

    # Output metrics
    output_duration_seconds: float | None = None  # Audio duration
    output_bytes: int | None = None  # Audio file size

    # Performance metrics
    latency_ms: int | None = None  # Request duration in milliseconds

    # Cost tracking
    total_cost: float = SQLField(default=0.0, ge=0)  # Calculated cost in USD

    # Status
    success: bool = SQLField(default=True)
    error_message: str | None = None
