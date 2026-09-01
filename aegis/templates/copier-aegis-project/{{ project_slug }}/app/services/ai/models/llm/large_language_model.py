"""Large Language Model catalog model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .llm_deployment import LLMDeployment
    from .llm_modality import LLMModality
    from .llm_org import LLMOrg
    from .llm_price import LLMPrice


class LargeLanguageModel(SQLModel, table=True):
    """
    Represents an LLM model in the catalog (e.g., gpt-4o, claude-3-5-sonnet).

    Stores model metadata including capabilities and configuration.
    """

    __tablename__ = "large_language_model"

    id: int | None = Field(default=None, primary_key=True)
    model_id: str = Field(unique=True, index=True)
    title: str
    description: str = Field(default="")
    context_window: int = Field(default=4096, gt=0)
    training_data: str = Field(default="")
    streamable: bool = Field(default=True)
    enabled: bool = Field(default=True)
    color: str = Field(default="#6B7280")
    icon_path: str = Field(default="")
    license: str | None = None
    source_url: str | None = None
    released_on: datetime | None = None
    family: str | None = None

    # Foreign key
    # The two org axes, both pointing at llm_org: who SERVES this model
    # (whose endpoint you call) and who MADE it (whose weights these
    # are). They are the same org for a first-party model and differ
    # wherever something serves weights it did not build.
    served_by_org_id: int | None = Field(
        default=None, foreign_key="llm_org.id", index=True
    )
    made_by_org_id: int | None = Field(
        default=None, foreign_key="llm_org.id", index=True
    )

    # Relationships
    served_by: "LLMOrg" = Relationship(
        back_populates="models_served",
        sa_relationship_kwargs={"foreign_keys": "LargeLanguageModel.served_by_org_id"},
    )
    made_by: "LLMOrg" = Relationship(
        back_populates="models_made",
        sa_relationship_kwargs={"foreign_keys": "LargeLanguageModel.made_by_org_id"},
    )
    modalities: list["LLMModality"] = Relationship(back_populates="llm")
    llm_prices: list["LLMPrice"] = Relationship(back_populates="llm")
    deployments: list["LLMDeployment"] = Relationship(back_populates="llm")

    def __repr__(self) -> str:
        return f"<LargeLanguageModel title={self.title} model_id={self.model_id}>"
