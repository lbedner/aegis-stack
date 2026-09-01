"""Organizations in the model economy: makers, servers, or both.

One table because they are one KIND of thing wearing different hats.
OpenAI both builds weights and serves them; Meta builds and serves
nothing; DeepInfra serves and builds nothing. Modelling "vendor" and
"lab" as separate tables duplicated every org that does both and left
no answer for "is this the same OpenAI?" - it is, and now it is one
row, with ``roles`` saying which hats it wears.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

from app.services.ai.models.agents.timestamps import utcnow_naive

if TYPE_CHECKING:
    from .large_language_model import LargeLanguageModel
    from .llm_deployment import LLMDeployment
    from .llm_org_role import LLMOrgRole
    from .llm_price import LLMPrice


class LLMOrg(SQLModel, table=True):
    """An organization that makes and/or serves language models."""

    __tablename__ = "llm_org"

    id: int | None = Field(default=None, primary_key=True)
    # Stable identifier: the registry's org namespace where one exists
    # ("meta-models"), else the catalog's provider key ("fireworks").
    slug: str = Field(unique=True, index=True)
    name: str = Field(index=True)
    description: str | None = None
    homepage: str | None = None
    # Base64 PNG, the same currency vendor and payee icons speak.
    icon_b64: str | None = None
    color: str = Field(default="#6B7280")
    icon_path: str = Field(default="")
    # Serving facts; null for an org that only publishes weights.
    api_base: str | None = None
    auth_method: str = Field(default="api-key")
    source: str = Field(default="catalog")
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime | None = None

    roles: list["LLMOrgRole"] = Relationship(
        back_populates="org", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    # Two distinct relationships to the same table: an org can appear on
    # a model as its maker, its server, or both.
    models_made: list["LargeLanguageModel"] = Relationship(
        back_populates="made_by",
        sa_relationship_kwargs={"foreign_keys": "LargeLanguageModel.made_by_org_id"},
    )
    models_served: list["LargeLanguageModel"] = Relationship(
        back_populates="served_by",
        sa_relationship_kwargs={"foreign_keys": "LargeLanguageModel.served_by_org_id"},
    )
    llm_prices: list["LLMPrice"] = Relationship(back_populates="org")
    deployments: list["LLMDeployment"] = Relationship(back_populates="org")

    def __repr__(self) -> str:
        return f"<LLMOrg slug={self.slug} name={self.name}>"
