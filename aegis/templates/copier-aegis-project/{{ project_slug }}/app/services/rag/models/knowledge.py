"""Knowledge base metadata models (DB-backed, agent-scoped RAG).

A ``KnowledgeBase`` maps 1:1 onto a Chroma collection by ``name``;
``Agent.knowledge_base_ids`` holds these names to scope retrieval.
Sources track per-document ingestion state and the chunking preset.
Kept out of ``models/__init__`` on purpose: that package is pure
pydantic and must stay importable on stacks without a database.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class KnowledgeBase(SQLModel, table=True):
    """A named knowledge base backed by one Chroma collection."""

    __tablename__ = "knowledge_base"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: str | None = None
    category: str | None = None
    meta_data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeBaseSource(SQLModel, table=True):
    """A source document within a knowledge base.

    ``loaded`` flips once the source is chunked and embedded;
    ``chunking_strategy`` picks the chunker preset (paragraph, sentence,
    fixed, code).
    """

    __tablename__ = "knowledge_base_source"

    id: int | None = Field(default=None, primary_key=True)
    knowledge_base_id: int = Field(foreign_key="knowledge_base.id", index=True)
    name: str
    file_path: str | None = None
    content_type: str | None = None
    chunking_strategy: str = Field(default="paragraph")
    loaded: bool = Field(default=False)
    meta_data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
