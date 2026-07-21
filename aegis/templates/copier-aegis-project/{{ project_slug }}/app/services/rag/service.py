"""
RAG service core implementation.

This module provides the main RAGService class that handles document loading,
chunking, indexing, and semantic search functionality.
"""

import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.log import logger

from .chunking import DocumentChunker
from .config import RAGServiceConfig
from .ids import get_file_hash
from .loaders import CodebaseLoader
from .models import Document, FileIndexResult, IndexedFile, IndexStats, SearchResult
from .vectorstore import VectorStoreManager


class RAGServiceError(Exception):
    """Base exception for RAG service errors."""

    pass


class LoaderError(RAGServiceError):
    """Exception raised when document loading fails."""

    pass


class IndexingError(RAGServiceError):
    """Exception raised when indexing fails."""

    pass


class SearchError(RAGServiceError):
    """Exception raised when search fails."""

    pass


class RAGService:
    """
    Core RAG service for document retrieval.

    Handles document loading, chunking, indexing to ChromaDB,
    and semantic search with built-in embeddings.

    Example:
        ```python
        from app.services.rag.config import get_rag_config
        from app.services.rag.service import RAGService
        from app.core.config import settings

        config = get_rag_config(settings)
        rag = RAGService(config)

        # Index codebase
        await rag.refresh_index("./app", "my-codebase")

        # Search
        results = await rag.search("how does auth work?", "my-codebase")
        for r in results:
            print(f"{r.metadata['source']}: {r.content[:100]}...")
        ```
    """

    def __init__(self, config: RAGServiceConfig):
        """Initialize RAG service with configuration."""
        self.config = config
        self.loader = CodebaseLoader()
        self.chunker = DocumentChunker(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
        )
        self.vectorstore = VectorStoreManager(
            persist_directory=self.config.persist_directory,
            embedding_provider=self.config.embedding_provider,
            embedding_model=self.config.embedding_model,
            openai_api_key=self.config.openai_api_key,
            model_cache_dir=self.config.model_cache_dir,
        )
        self._last_activity: datetime | None = None

    # ============================================
    # Core Async Functions (scheduler/worker ready)
    # ============================================

    async def load_documents(
        self,
        path: str | Path,
        extensions: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> list[Document]:
        """
        Load source files from a path.

        Args:
            path: File or directory path to load
            extensions: File extensions to include (e.g., [".py", ".md"])
            exclude_patterns: Glob patterns to exclude (e.g., ["**/test_*"])

        Returns:
            list[Document]: Loaded documents with metadata

        Raises:
            LoaderError: If loading fails
        """
        try:
            documents = await self.loader.load(path, extensions, exclude_patterns)
            self._last_activity = datetime.now(UTC)
            return documents
        except FileNotFoundError as e:
            raise LoaderError(f"Path not found: {path}") from e
        except Exception as e:
            raise LoaderError(f"Failed to load documents: {e}") from e

    async def chunk_documents(
        self,
        documents: list[Document],
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> list[Document]:
        """
        Split documents into chunks for indexing.

        Args:
            documents: Documents to chunk
            chunk_size: Override default chunk size
            chunk_overlap: Override default overlap

        Returns:
            list[Document]: Chunked documents with preserved metadata
        """
        chunks = await self.chunker.chunk(documents, chunk_size, chunk_overlap)
        self._last_activity = datetime.now(UTC)
        return chunks

    async def index_documents(
        self,
        documents: list[Document],
        collection_name: str,
        metadata_fields: list[str] | None = None,
        progress_callback: Callable[[int, int, int], None] | None = None,
    ) -> IndexStats:
        """
        Add documents to ChromaDB collection.

        Args:
            documents: Documents (or chunks) to index
            collection_name: ChromaDB collection name
            metadata_fields: Which metadata fields to include
            progress_callback: Optional callback(batch_num, total_batches, chunks_processed)

        Returns:
            IndexStats: Statistics about the indexing operation

        Raises:
            IndexingError: If indexing fails
        """
        try:
            stats = await self.vectorstore.add_documents(
                documents, collection_name, metadata_fields, progress_callback
            )
            self._last_activity = datetime.now(UTC)

            logger.info(
                "rag_service.index_documents",
                collection=collection_name,
                documents=stats.documents_added,
                total=stats.total_documents,
                duration_ms=round(stats.duration_ms, 2),
            )

            return stats
        except Exception as e:
            raise IndexingError(f"Failed to index documents: {e}") from e

    async def search(
        self,
        query: str,
        collection_name: str,
        top_k: int | None = None,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """
        Query vector store for relevant documents.

        Args:
            query: Search query text
            collection_name: ChromaDB collection to search
            top_k: Number of results to return (default from config)
            filter_metadata: Optional metadata filter

        Returns:
            list[SearchResult]: Ranked search results with scores

        Raises:
            SearchError: If search fails
        """
        try:
            k = top_k or self.config.default_top_k
            results = await self.vectorstore.search(
                query, collection_name, k, filter_metadata
            )
            self._last_activity = datetime.now(UTC)
            return results
        except Exception as e:
            raise SearchError(f"Failed to search: {e}") from e

    async def search_scoped(
        self,
        query: str,
        allowed_collections: Sequence[str],
        top_k: int | None = None,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """
        Search across an agent's allowed collections, merged and ranked.

        Each collection is searched independently; results are merged,
        sorted by similarity score, and cut to top_k overall. A missing
        or failing collection is skipped with a warning so a stale scope
        entry degrades that one collection, never the whole request.

        Args:
            query: Search query text
            allowed_collections: Collection names the caller may search
            top_k: Number of results overall (default from config)
            filter_metadata: Optional metadata filter

        Returns:
            list[SearchResult]: Ranked results from allowed collections
        """
        k = top_k or self.config.default_top_k
        merged: list[SearchResult] = []
        for collection_name in allowed_collections:
            try:
                merged.extend(
                    await self.search(query, collection_name, k, filter_metadata)
                )
            except SearchError as e:
                logger.warning(
                    "rag.search_scoped.collection_skipped",
                    collection=collection_name,
                    error=str(e),
                )
        merged.sort(key=lambda r: r.score, reverse=True)
        return merged[:k]

    async def refresh_index(
        self,
        path: str | Path,
        collection_name: str,
        extensions: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        progress_callback: Callable[[int, int, int], None] | None = None,
    ) -> IndexStats:
        """
        Full reindex: load, chunk, and index documents.

        Convenience method that combines load_documents,
        chunk_documents, and index_documents into a single operation.
        Deletes existing collection before reindexing.

        Args:
            path: File or directory path to load
            collection_name: ChromaDB collection name
            extensions: File extensions to include
            exclude_patterns: Glob patterns to exclude
            progress_callback: Optional callback(batch_num, total_batches, chunks_processed)

        Returns:
            IndexStats: Statistics about the indexing operation
        """
        logger.debug(
            "rag_service.refresh_index.start",
            path=str(path),
            collection=collection_name,
        )

        # Delete existing collection
        await self.vectorstore.delete_collection(collection_name)

        # Phase 1: Load documents
        load_start = time.perf_counter()
        documents = await self.load_documents(path, extensions, exclude_patterns)
        load_ms = (time.perf_counter() - load_start) * 1000

        if not documents:
            logger.warning(
                "rag_service.refresh_index.no_documents",
                path=str(path),
            )
            return IndexStats(
                collection_name=collection_name,
                documents_added=0,
                total_documents=0,
                source_files=0,
                extensions=[],
                duration_ms=0.0,
                load_ms=load_ms,
                chunk_ms=0.0,
            )

        # Extract source file info before chunking
        source_file_count = len(documents)
        extensions_found = sorted(
            {
                doc.metadata.get("extension", "")
                for doc in documents
                if doc.metadata.get("extension")
            }
        )

        # Phase 2: Chunk documents
        chunk_start = time.perf_counter()
        chunks = await self.chunk_documents(documents)
        chunk_ms = (time.perf_counter() - chunk_start) * 1000

        # Phase 3: Index chunks (already timed internally, returned as duration_ms)
        stats = await self.index_documents(
            chunks, collection_name, progress_callback=progress_callback
        )

        # Add phase timing and source file info to stats
        stats.load_ms = load_ms
        stats.chunk_ms = chunk_ms
        stats.source_files = source_file_count
        stats.extensions = extensions_found

        logger.debug(
            "rag_service.refresh_index.complete",
            collection=collection_name,
            source_docs=len(documents),
            chunks=stats.documents_added,
            load_ms=round(load_ms, 2),
            chunk_ms=round(chunk_ms, 2),
            index_ms=round(stats.duration_ms, 2),
        )

        return stats

    # ============================================
    # File-Level Operations
    # ============================================

    async def add_file(
        self,
        path: str | Path,
        collection_name: str,
    ) -> FileIndexResult:
        """
        Add or update a single file in the collection.

        Uses upsert semantics: if the file was previously indexed,
        its chunks are updated. Otherwise, new chunks are created.

        Args:
            path: Path to the file to index
            collection_name: Target collection name

        Returns:
            FileIndexResult: Result with chunk IDs and action taken

        Raises:
            LoaderError: If file cannot be loaded
            IndexingError: If indexing fails
        """
        file_path = Path(path)
        if not file_path.is_file():
            raise LoaderError(f"Path is not a file: {path}")

        # Load the single file
        documents = await self.loader.load(file_path)
        if not documents:
            raise LoaderError(f"No content loaded from: {path}")

        # Chunk the file
        chunks = await self.chunker.chunk(documents)

        # Index chunks (upsert will update existing)
        stats = await self.vectorstore.add_documents(chunks, collection_name)

        source_path = str(file_path.absolute())
        file_hash = get_file_hash(source_path)

        logger.debug(
            "rag_service.add_file",
            file=str(path),
            collection=collection_name,
            chunks=len(chunks),
        )

        return FileIndexResult(
            file_path=source_path,
            file_hash=file_hash,
            chunk_ids=stats.chunk_ids,
            chunk_count=len(chunks),
            action="added",
        )

    async def remove_file(
        self,
        source_path: str,
        collection_name: str,
    ) -> FileIndexResult:
        """
        Remove all chunks for a specific file from the collection.

        Args:
            source_path: The source path as stored in metadata
            collection_name: Target collection name

        Returns:
            FileIndexResult: Result with count of removed chunks
        """
        count = await self.vectorstore.remove_by_source(collection_name, source_path)

        file_hash = get_file_hash(source_path)

        logger.debug(
            "rag_service.remove_file",
            file=source_path,
            collection=collection_name,
            chunks_removed=count,
        )

        return FileIndexResult(
            file_path=source_path,
            file_hash=file_hash,
            chunk_ids=[],
            chunk_count=count,
            action="removed",
        )

    async def list_files(
        self,
        collection_name: str,
    ) -> list[IndexedFile]:
        """
        List all files indexed in a collection.

        Args:
            collection_name: Collection to query

        Returns:
            list[IndexedFile]: List of files with chunk counts
        """
        raw_files = await self.vectorstore.list_indexed_files(collection_name)
        return [IndexedFile(source=f["source"], chunks=f["chunks"]) for f in raw_files]

    # ============================================
    # Collection Management
    # ============================================

    async def list_collections(self) -> list[str]:
        """List all ChromaDB collections."""
        return await self.vectorstore.list_collections()

    async def get_collection_stats(self, collection_name: str) -> dict[str, Any] | None:
        """Get statistics for a collection."""
        info = await self.vectorstore.get_collection_info(collection_name)
        if info:
            return info.model_dump()
        return None

    async def delete_collection(self, collection_name: str) -> bool:
        """Delete a ChromaDB collection."""
        return await self.vectorstore.delete_collection(collection_name)

    # ============================================
    # Service Status & Health
    # ============================================

    def get_service_status(self) -> dict[str, Any]:
        """Get current service status and metrics."""
        return {
            "enabled": self.config.enabled,
            "persist_directory": self.config.persist_directory,
            "embedding_provider": self.config.embedding_provider,
            "embedding_model": self.config.embedding_model,
            "chunk_size": self.config.chunk_size,
            "chunk_overlap": self.config.chunk_overlap,
            "default_top_k": self.config.default_top_k,
            "last_activity": self._last_activity.isoformat()
            if self._last_activity
            else None,
        }

    def validate_service(self) -> list[str]:
        """Validate service configuration and return any issues."""
        return self.config.validate_configuration()
