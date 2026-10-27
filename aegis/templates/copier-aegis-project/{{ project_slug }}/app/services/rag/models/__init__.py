"""
RAG service data models.

This module defines the core data structures for document handling,
search results, and indexing statistics.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class Document(BaseModel):
    """
    A document with content and metadata.

    Used throughout the RAG pipeline for loading, chunking, and indexing.
    """

    content: str = Field(..., description="Document text content")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Document metadata (source, file_name, extension, etc.)",
    )

    def __len__(self) -> int:
        """Return content length."""
        return len(self.content)


class SearchResult(BaseModel):
    """
    A search result from the vector store.

    Contains the matched content, similarity score, and original metadata.
    """

    content: str = Field(..., description="Matched document content")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Document metadata",
    )
    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Similarity score (0-1, higher is more similar)",
    )
    rank: int = Field(..., ge=1, description="Result rank (1 = most relevant)")


class IndexStats(BaseModel):
    """
    Statistics from an indexing operation.

    Returned after adding documents to the vector store.
    """

    collection_name: str = Field(..., description="Name of the collection")
    documents_added: int = Field(..., ge=0, description="Number of documents added")
    total_documents: int = Field(..., ge=0, description="Total documents in collection")
    source_files: int = Field(
        default=0, ge=0, description="Number of source files indexed"
    )
    extensions: list[str] = Field(
        default_factory=list,
        description="File extensions that were indexed",
    )
    duration_ms: float = Field(
        ..., ge=0.0, description="Vectorstore operation duration in ms"
    )
    load_ms: float = Field(
        default=0.0, ge=0.0, description="Document loading duration in ms"
    )
    chunk_ms: float = Field(
        default=0.0, ge=0.0, description="Document chunking duration in ms"
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    chunk_ids: list[str] = Field(
        default_factory=list,
        description="IDs of chunks that were added/updated",
    )


class CollectionInfo(BaseModel):
    """Information about a vector store collection."""

    name: str = Field(..., description="Collection name")
    count: int = Field(..., ge=0, description="Number of chunks")
    doc_count: int = Field(0, ge=0, description="Number of unique documents/files")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Collection metadata",
    )


class FileIndexResult(BaseModel):
    """
    Result from a file-level indexing operation.

    Returned when adding, removing, or updating individual files.
    """

    file_path: str = Field(..., description="Path of the file that was processed")
    file_hash: str = Field(..., description="Hash prefix used for chunk IDs")
    chunk_ids: list[str] = Field(
        default_factory=list,
        description="IDs of chunks for this file",
    )
    chunk_count: int = Field(..., ge=0, description="Number of chunks")
    action: str = Field(
        ...,
        description="Action performed: 'added', 'removed', or 'updated'",
    )


class IndexedFile(BaseModel):
    """Information about an indexed file in a collection."""

    source: str = Field(..., description="Source file path")
    chunks: int = Field(..., ge=0, description="Number of chunks from this file")
    # Its latest chunk's, None where it was indexed before chunks said when.
    indexed_at: datetime | None = None
    content_type: str | None = None  # the loader's file type


__all__ = [
    "Document",
    "SearchResult",
    "IndexStats",
    "CollectionInfo",
    "FileIndexResult",
    "IndexedFile",
]
