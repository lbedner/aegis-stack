"""Conversation sentiment analysis model."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, ForeignKey, String
from sqlmodel import Field, SQLModel

SENTIMENT_VALUES = ("positive", "neutral", "negative", "frustrated")
PERFORMANCE_VALUES = ("good", "acceptable", "poor")


class SentimentAnalysis(SQLModel, table=True):
    """
    One sentiment verdict per conversation, written by the batch scoring
    job. ``conversation_id`` is unique (score-once) and rows die with
    their conversation via ON DELETE CASCADE.
    """

    __tablename__ = "sentiment_analysis"

    id: int | None = Field(default=None, primary_key=True)
    conversation_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey("conversation.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        )
    )
    overall_sentiment: str
    overall_score: float
    assistant_performance: str
    issues: list[Any] = Field(default_factory=list, sa_column=Column(JSON))
    summary: str | None = None
    model_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
