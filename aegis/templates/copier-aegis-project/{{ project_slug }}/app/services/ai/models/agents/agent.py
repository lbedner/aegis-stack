"""Agent registry model."""

from datetime import UTC, datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel

from .agent_tool import AgentTool
from .tool import Tool


class Agent(SQLModel, table=True):
    """
    A database-driven agent definition.

    Agents are the AI service's default architecture: every chat request
    resolves an agent (the seeded ``assistant`` by default) and hydrates
    the runtime from this row. ``model_id`` is a plain catalog reference
    (NOT a foreign key, matching ``llm_usage``: the catalog is ETL-synced
    and rows churn); ``None`` means "use the service's active model".
    """

    __tablename__ = "agent"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    description: str | None = None
    category: str | None = None
    model_id: str | None = Field(default=None, index=True)
    system_prompt: str
    temperature: float = Field(default=0.7)
    max_tokens: int = Field(default=1000)
    memory_modules: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    knowledge_base_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    tools: list[Tool] = Relationship(link_model=AgentTool)
