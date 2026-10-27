"""Knowledge base metadata models (DB-backed, agent-scoped RAG).

A ``KnowledgeBase`` maps 1:1 onto a Chroma collection by ``name``, and a
``KnowledgeBaseSource`` onto a file indexed into it: records of what the
index holds, brought up to it by ``knowledge.sync`` (its chunks and when
it was indexed in ``meta_data``);
``Agent.knowledge_base_ids`` holds these names to scope retrieval.
Kept out of ``models/__init__`` on purpose: that package is pure
pydantic and must stay importable on stacks without a database.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.core.figures import FIGURES
from app.core.time import utcnow


class KnowledgeBase(SQLModel, table=True):
    """A named knowledge base backed by one Chroma collection."""

    __tablename__ = "knowledge_base"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: str | None = None
    category: str | None = None
    meta_data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class KnowledgeBaseSource(SQLModel, table=True):
    """A file the index holds within a knowledge base. ``chunking_strategy``
    is not chosen per source yet: every file is chunked by the RAG
    settings."""

    __tablename__ = "knowledge_base_source"

    id: int | None = Field(default=None, primary_key=True)
    knowledge_base_id: int = Field(foreign_key="knowledge_base.id", index=True)
    name: str
    file_path: str | None = None
    content_type: str | None = None
    chunking_strategy: str = Field(default="paragraph")
    loaded: bool = Field(default=False)
    meta_data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class SourceRecord(BaseModel):
    """A source as the records hold it."""

    model_config = FIGURES

    name: str
    file_path: str | None
    content_type: str | None
    chunks: int
    indexed_at: datetime | None


class KnowledgeRecord(BaseModel):
    """A knowledge base, what it is for and what it holds."""

    model_config = FIGURES

    name: str
    description: str | None
    sources: list[SourceRecord]
