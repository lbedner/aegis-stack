"""
RAG stats context models for AI awareness.

This module provides data structures for managing RAG service status
injection into chat conversations, giving Illiana awareness of indexed
collections, document counts, and RAG configuration.
"""

from typing import Any

from pydantic import BaseModel, Field


class RAGStatsContext(BaseModel):
    """
    Context from RAG service status for injection into prompts.

    Gives the AI awareness about indexed collections, document counts,
    embedding configuration, and RAG service status.
    """

    enabled: bool = Field(default=False, description="Whether RAG is enabled")
    collection_count: int = Field(default=0, description="Number of collections")
    collections: list[dict[str, Any]] = Field(
        default_factory=list, description="Collection names and doc counts"
    )
    embedding_model: str | None = Field(
        default=None, description="Embedding model in use"
    )
    chunk_size: int | None = Field(default=None, description="Chunk size setting")
    chunk_overlap: int | None = Field(default=None, description="Chunk overlap setting")
    default_top_k: int | None = Field(
        default=None, description="Default top_k for searches"
    )
    last_activity: str | None = Field(
        default=None, description="Last activity timestamp"
    )

    def format_for_prompt(self, compact: bool = False) -> str:
        """
        Format RAG stats for injection into system prompt.

        Args:
            compact: Whether to use ultra-compact format for smaller models (Ollama)

        Returns:
            Formatted string for prompt injection
        """
        if not self.enabled:
            return "RAG: disabled"

        # Ultra-compact mode for Ollama and smaller models
        if compact:
            total_docs = sum(c.get("count", 0) for c in self.collections)
            return (
                f"RAG: {self.collection_count} collections, {total_docs:,} docs indexed"
            )

        lines = []

        # Status line
        status_parts = ["RAG: enabled"]
        status_parts.append(f"{self.collection_count} collections")
        if self.embedding_model:
            status_parts.append(f"embedding: {self.embedding_model}")
        lines.append(" | ".join(status_parts))

        # Collections with doc counts
        if self.collections:
            coll_parts = []
            for coll in self.collections:
                name = coll.get("name", "unknown")
                count = coll.get("count", 0)
                coll_parts.append(f"{name} ({count:,} docs)")
            lines.append(f"Collections: {', '.join(coll_parts)}")

        # Config line
        config_parts = []
        if self.chunk_size:
            config_parts.append(f"chunk_size={self.chunk_size}")
        if self.chunk_overlap:
            config_parts.append(f"overlap={self.chunk_overlap}")
        if self.default_top_k:
            config_parts.append(f"top_k={self.default_top_k}")
        if config_parts:
            lines.append(f"Config: {', '.join(config_parts)}")

        # Last activity
        if self.last_activity:
            lines.append(f"Last activity: {self.last_activity}")

        lines.append(
            "  Report these stats when asked about RAG, "
            "collections, or indexed documents."
        )

        return "\n".join(lines)

    def to_metadata(self) -> dict[str, Any]:
        """
        Convert RAG stats context to metadata format for storage.

        Returns:
            Summary metadata dictionary
        """
        return {
            "enabled": self.enabled,
            "collection_count": self.collection_count,
            "collections": [c.get("name") for c in self.collections],
            "embedding_model": self.embedding_model,
        }


__all__ = ["RAGStatsContext"]
