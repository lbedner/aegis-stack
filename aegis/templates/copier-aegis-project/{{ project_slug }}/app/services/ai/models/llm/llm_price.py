"""LLM Price model for token pricing with versioning."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .large_language_model import LargeLanguageModel
    from .llm_org import LLMOrg


# The voice rates, by column name: the sync and the offline seed copy
# these from the source catalog.
VOICE_PRICE_FIELDS = (
    "input_cost_per_audio_token",
    "output_cost_per_audio_token",
    "input_cost_per_second",
    "output_cost_per_second",
    "input_cost_per_character",
)
# Every rate a cost reads, by column name: what a price lookup hands back.
RATE_FIELDS = (
    "input_cost_per_token",
    "output_cost_per_token",
    "cache_input_cost_per_token",
    *VOICE_PRICE_FIELDS,
)


class LLMPrice(SQLModel, table=True):
    """
    Token pricing for an LLM model from a specific vendor.

    Supports price versioning via effective_date - the latest price
    by effective_date is used for cost calculation.
    """

    __tablename__ = "llm_price"

    id: int | None = Field(default=None, primary_key=True)
    org_id: int = Field(foreign_key="llm_org.id", index=True)
    llm_id: int = Field(foreign_key="large_language_model.id", index=True)
    input_cost_per_token: float = Field(ge=0)
    output_cost_per_token: float = Field(ge=0)
    cache_input_cost_per_token: float | None = Field(default=None, ge=0)
    # Voice. A model bills by whichever measures it lists, and may list
    # several (a realtime model: text AND audio tokens); None is "not
    # billed this way", never zero. Named as the source catalog names them.
    input_cost_per_audio_token: float | None = Field(default=None, ge=0)
    output_cost_per_audio_token: float | None = Field(default=None, ge=0)
    input_cost_per_second: float | None = Field(default=None, ge=0)
    output_cost_per_second: float | None = Field(default=None, ge=0)
    input_cost_per_character: float | None = Field(default=None, ge=0)
    effective_date: datetime = Field(
        default_factory=lambda: datetime.now(UTC), index=True
    )

    # Relationships
    org: "LLMOrg" = Relationship(back_populates="llm_prices")
    llm: "LargeLanguageModel" = Relationship(back_populates="llm_prices")
