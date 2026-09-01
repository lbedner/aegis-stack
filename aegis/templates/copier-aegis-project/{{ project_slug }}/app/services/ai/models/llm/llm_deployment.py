"""LLM Deployment model for performance characteristics."""

from typing import TYPE_CHECKING

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .large_language_model import LargeLanguageModel
    from .llm_org import LLMOrg


class LLMDeployment(SQLModel, table=True):
    """
    Performance characteristics and feature flags for an LLM deployment.

    The same model can have different deployments across vendors
    with varying performance characteristics.
    """

    __tablename__ = "llm_deployment"
    __table_args__ = (
        UniqueConstraint("llm_id", "org_id", name="unique_llm_org_deployment"),
    )

    id: int | None = Field(default=None, primary_key=True)
    llm_id: int = Field(foreign_key="large_language_model.id", index=True)
    org_id: int = Field(foreign_key="llm_org.id", index=True)

    # Performance ratings (0-100 scale)
    speed: int = Field(default=50, ge=0, le=100)
    intelligence: int = Field(default=50, ge=0, le=100)
    reasoning: int = Field(default=50, ge=0, le=100)

    # Capabilities
    output_max_tokens: int = Field(default=4096, gt=0)
    function_calling: bool = Field(default=False)
    input_cache: bool = Field(default=False)
    structured_output: bool = Field(default=False)

    # Relationships
    llm: "LargeLanguageModel" = Relationship(back_populates="deployments")
    org: "LLMOrg" = Relationship(back_populates="deployments")
