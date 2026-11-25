"""Agent registry model."""

from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel

from app.core.time import utcnow
from app.services.ai.models.llm import LargeLanguageModel

from .agent_tool import AgentTool
from .tool import Tool


class Agent(SQLModel, table=True):
    """
    A database-driven agent definition.

    Agents are the AI service's default architecture: every chat request
    resolves an agent (the seeded ``assistant`` by default) and hydrates
    the runtime from this row. ``llm`` is the catalog model it runs on, on
    the provider that serves it; ``None`` means "use the service's active
    model".
    """

    __tablename__ = "agent"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    description: str | None = None
    category: str | None = None
    llm_id: int | None = Field(
        default=None, foreign_key="large_language_model.id", index=True
    )
    system_prompt: str
    temperature: float = Field(default=0.7)
    max_tokens: int = Field(default=1000)
    # A server default too: the column replaced ``memory_modules`` on tables
    # that already had rows, which the rename's revision then fills.
    context_modules: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False, server_default="[]")
    )
    knowledge_base_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    is_active: bool = Field(default=True)
    # Grants this agent sandboxed code execution (code mode): the model
    # writes Python that calls the agent's granted tools as functions and
    # runs it in the Monty interpreter. Off by default; flipping it is a
    # capability grant, deliberately DB-driven like tool attachments.
    code_mode: bool = Field(default=False)
    # The agent this one extends, one level deep: its section goes in front
    # of the parent's prompt, and tools, context modules and knowledge
    # bases come from the parent unless this row names its own. Model,
    # sampling and code mode are always this row's own.
    extends: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    tools: list[Tool] = Relationship(link_model=AgentTool)
    # Loaded with the row: every reader of an agent shows its model.
    llm: LargeLanguageModel | None = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )

    @property
    def model_id(self) -> str | None:
        """The pinned model's catalog id; None follows the active model."""
        return self.llm.model_id if self.llm else None
