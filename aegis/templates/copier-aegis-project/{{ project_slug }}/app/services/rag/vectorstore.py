"""
ChromaDB vector store integration for RAG service.

Supports configurable embedding providers:
- sentence-transformers (default): Local embeddings via SentenceTransformers
- openai: OpenAI API embeddings
"""

import asyncio
from collections import Counter
from collections.abc import Callable, Collection
from datetime import datetime
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.errors import NotFoundError

from app.core import cpus, secrets
from app.core.log import logger

from .models import (
    CollectionInfo,
    Document,
    Embedded,
    IndexedFile,
    IndexStats,
    SearchResult,
)
from .shaping import build_where_clause, deduplicate_results, prepare
from .uploads import check_name


class VectorStoreError(Exception):
    """Base exception for vector store errors."""

    pass


class CollectionNotFoundError(VectorStoreError):
    """Raised when a collection is not found."""

    pass


class VectorStoreManager:
    """Manages ChromaDB collections and operations."""

    def __init__(
        self,
        persist_directory: str = "./data/chromadb",
        embedding_provider: str = "sentence-transformers",
        embedding_model: str = "BAAI/bge-small-en-v1.5",
        openai_api_key: str | None = None,
        model_cache_dir: str | None = None,
    ):
        """
        Initialize vector store manager.

        Args:
            persist_directory: Directory for ChromaDB persistence
            embedding_provider: Provider to use ('sentence-transformers' or 'openai')
            embedding_model: Model name for the selected provider
            openai_api_key: API key for OpenAI embeddings (required if provider is 'openai')
            model_cache_dir: Directory for model cache (None = system default)
        """
        self.persist_directory = Path(persist_directory)
        self.embedding_provider = embedding_provider
        self.embedding_model = embedding_model
        self.openai_api_key = openai_api_key
        self.model_cache_dir = model_cache_dir
        self._client: chromadb.ClientAPI | None = None
        self._embedding_function: Any = None
        # The key the cached OpenAI embedding function was built with.
        self._embedding_key: str | None = None
        # Threads a local model embeds with: one CPU left for a server's own
        # work by default; a worker, with nothing else waiting, sets all.
        self.threads: int | None = None
        # One embedding call at a time in this process (``embed``), and one
        # load of the model however many ask for it at once (``_embedding``).
        self._embedding_lock = asyncio.Lock()
        self._loading = asyncio.Lock()

    @property
    def client(self) -> chromadb.ClientAPI:
        """Get or create ChromaDB client (lazy initialization)."""
        if self._client is None:
            self.persist_directory.mkdir(parents=True, exist_ok=True)

            self._client = chromadb.PersistentClient(
                path=str(self.persist_directory),
                settings=ChromaSettings(
                    anonymized_telemetry=False,
                    allow_reset=True,
                ),
            )
            logger.debug(
                "vectorstore.initialized",
                persist_directory=str(self.persist_directory),
            )

        return self._client

    async def _embedding(self) -> Any:
        """The embedding function for the configured provider, built once.
        OpenAI's key is read now (``.env``, then the secrets store) and the
        function rebuilt when it changes, so a key saved while the app runs
        is used. Built in a thread: loading a local model takes seconds, and
        the server answers everything else meanwhile."""
        # OpenAI embeds with its key; the local model downloads with the
        # Hugging Face token, when one is set.
        key = (
            self.openai_api_key or await secrets.get("OPENAI_API_KEY")
            if self.embedding_provider == "openai"
            else await secrets.get("HF_TOKEN")
        )
        async with self._loading:
            if self._embedding_function is None or key != self._embedding_key:
                self._embedding_function = await asyncio.to_thread(
                    self._create_embedding_function, key
                )
                self._embedding_key = key
        return self._embedding_function

    async def _open(self, collection_name: str) -> Any:
        """``collection_name`` opened for what embeds nothing (counting,
        listing, removing, storing vectors embedded already), so the model
        is never loaded for it. NotFoundError when it is not there."""
        return await asyncio.to_thread(self.client.get_collection, name=collection_name)

    def _create_embedding_function(self, key: str | None) -> Any:
        """Create embedding function based on configured provider."""
        if self.embedding_provider == "openai":
            if not key:
                raise VectorStoreError(
                    "OpenAI API key required when using openai embedding provider. "
                    "Set OPENAI_API_KEY in your environment."
                )
            from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

            logger.debug(
                "vectorstore.embedding.openai",
                model=self.embedding_model,
            )
            return OpenAIEmbeddingFunction(
                api_key=key,
                model_name=self.embedding_model,
            )
        else:
            # Default: sentence-transformers
            import logging
            import os

            # Keep the embedding-model load quiet for clean CLI/RAG output:
            # disable the HF/transformers download progress bar (must be set
            # before those libs import, below), authenticate the download if a
            # token is configured (drops the "unauthenticated requests"
            # warning), and silence sentence-transformers' INFO load line.
            os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
            if key:
                os.environ.setdefault("HF_TOKEN", key)
            logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
            # Threads by the container's CPUs, not the machine's (``threads``):
            # a capped container would otherwise starve.
            import torch

            torch.set_num_threads(self.threads or cpus.spare_one())

            from chromadb.utils.embedding_functions import (
                SentenceTransformerEmbeddingFunction,
            )

            logger.debug(
                "vectorstore.embedding.sentence_transformers",
                model=self.embedding_model,
                cache_dir=self.model_cache_dir,
            )
            # Pass cache_folder if specified (for local development)
            # In Docker, SENTENCE_TRANSFORMERS_HOME env var handles this
            if self.model_cache_dir:
                return SentenceTransformerEmbeddingFunction(
                    model_name=self.embedding_model,
                    cache_folder=self.model_cache_dir,
                )
            return SentenceTransformerEmbeddingFunction(
                model_name=self.embedding_model,
            )

    async def add_documents(
        self,
        documents: list[Document],
        collection_name: str,
        metadata_fields: list[str] | None = None,
        progress_callback: Callable[[int, int, int], None] | None = None,
    ) -> IndexStats:
        """Embed ``documents`` here and store them (upsert, by deterministic
        ids: indexing a file again replaces its chunks); ``progress_callback``
        (batch, batches, chunks) as each stored batch lands."""
        check_name(collection_name)  # before the embedding, not after it
        embedded = await self.embed(documents, metadata_fields)
        return await self.store(embedded, collection_name, progress_callback)

    async def embed(
        self, documents: list[Document], metadata_fields: list[str] | None = None
    ) -> Embedded:
        """Chunks to vectors, by the configured model: the slow part, run one
        call at a time in this process (each already spreads over every CPU
        it may use, so two at once only fight). Stores nothing: a worker's
        half, or this process's when there is no worker."""
        prepared = prepare(documents, metadata_fields)
        if not prepared.texts:
            return prepared
        model = await self._embedding()
        async with self._embedding_lock:
            vectors = await asyncio.to_thread(model, prepared.texts)
        return prepared.model_copy(
            update={"vectors": [[float(x) for x in v] for v in vectors]}
        )

    async def store(
        self,
        embedded: Embedded,
        collection_name: str,
        progress_callback: Callable[[int, int, int], None] | None = None,
    ) -> IndexStats:
        """Store chunks embedded already (here or by a worker), in batches of
        500, embedding nothing: the one writer's half, quick."""
        check_name(collection_name)
        start_time = asyncio.get_event_loop().time()
        try:
            collection = await self._open(collection_name)
        except NotFoundError:
            # A new collection records its model, so search embeds alike.
            collection = await asyncio.to_thread(
                self.client.create_collection,
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
                embedding_function=await self._embedding(),
            )
        size = 500
        batches = (len(embedded.ids) + size - 1) // size
        for n, at in enumerate(range(0, len(embedded.ids), size)):
            end = min(at + size, len(embedded.ids))
            await asyncio.to_thread(
                collection.upsert,
                ids=embedded.ids[at:end],
                documents=embedded.texts[at:end],
                metadatas=embedded.metadatas[at:end],  # type: ignore[arg-type]
                embeddings=embedded.vectors[at:end],  # type: ignore[arg-type]
            )
            if progress_callback:
                progress_callback(n + 1, batches, end)
        duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
        stats = IndexStats(
            collection_name=collection_name,
            documents_added=len(embedded.ids),
            total_documents=await asyncio.to_thread(collection.count),
            duration_ms=duration_ms,
            chunk_ids=embedded.ids,
        )
        logger.debug(
            "vectorstore.store",
            collection=collection_name,
            count=len(embedded.ids),
            duration_ms=round(duration_ms, 2),
        )
        return stats

    async def remove_by_source(
        self,
        collection_name: str,
        sources: list[str],
        keep: Collection[str] = (),
    ) -> int:
        """Remove every chunk of each of ``sources`` (files) but ``keep``
        (ids just stored over, the same ids, so a file read again loses
        only the chunks past its new end), in one call; the number removed."""
        try:
            collection = await self._open(collection_name)
        except NotFoundError:
            logger.warning(
                "vectorstore.collection_not_found",
                collection=collection_name,
            )
            return 0

        # Their ids only: the chunks' text and metadata are not needed.
        results = await asyncio.to_thread(
            collection.get, where={"source": {"$in": sources}}, include=[]
        )

        ids = [i for i in results["ids"] if i not in keep]
        if not ids:
            logger.debug(
                "vectorstore.remove_by_source.no_matches",
                collection=collection_name,
                sources=len(sources),
            )
            return 0

        # Delete the matching documents
        await asyncio.to_thread(collection.delete, ids=ids)

        logger.debug(
            "vectorstore.remove_by_source",
            collection=collection_name,
            sources=len(sources),
            count=len(ids),
        )

        return len(ids)

    async def list_indexed_files(
        self,
        collection_name: str,
    ) -> list[IndexedFile]:
        """
        List all unique source files indexed in a collection, each with
        its chunk count, when it was last indexed and what it is.

        Args:
            collection_name: Target collection
        """
        try:
            collection = await self._open(collection_name)
        except NotFoundError:
            return []

        # Every chunk's metadata, never its text
        results = await asyncio.to_thread(collection.get, include=["metadatas"])

        # Group by source: its chunks, its latest stamp, its type.
        chunks: Counter[str] = Counter()
        latest: dict[str, str] = {}
        kinds: dict[str, str] = {}
        for meta in results["metadatas"] or []:
            source = str(meta.get("source", "unknown"))
            chunks[source] += 1
            if stamp := meta.get("indexed_at"):
                latest[source] = max(latest.get(source, ""), str(stamp))
            if kind := meta.get("file_type"):
                kinds[source] = str(kind)

        return [
            IndexedFile(
                source=source,
                chunks=count,
                indexed_at=datetime.fromisoformat(latest[source])
                if source in latest
                else None,
                content_type=kinds.get(source),
            )
            for source, count in sorted(chunks.items())
        ]

    async def search(
        self,
        query: str,
        collection_name: str,
        top_k: int = 5,
        filter_metadata: dict[str, Any] | None = None,
        dedupe: bool = True,
    ) -> list[SearchResult]:
        """
        Search for relevant documents.

        Args:
            query: Search query text
            collection_name: Collection to search
            top_k: Number of results
            filter_metadata: Optional metadata filter
            dedupe: Remove near-duplicate results (default: True)

        Returns:
            list[SearchResult]: Ranked results with scores
        """
        try:
            collection = await asyncio.to_thread(
                self.client.get_collection,
                name=collection_name,
                embedding_function=await self._embedding(),
            )
        except NotFoundError:
            logger.warning(
                "vectorstore.collection_not_found",
                collection=collection_name,
            )
            return []

        # Build ChromaDB where clause
        where = None
        if filter_metadata:
            where = build_where_clause(filter_metadata)

        # Query for more results if deduping (to ensure enough unique results)
        query_k = top_k * 3 if dedupe else top_k

        # Query collection
        results = await asyncio.to_thread(
            collection.query,
            query_texts=[query],
            n_results=query_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        # Convert to SearchResult objects
        search_results: list[SearchResult] = []

        if results["documents"] and results["documents"][0]:
            for i, doc_text in enumerate(results["documents"][0]):
                # ChromaDB returns distance, convert to similarity score
                distance = results["distances"][0][i] if results["distances"] else 0.0
                # For cosine distance, similarity = 1 - distance
                # But distance can be > 1 for non-normalized vectors
                score = max(0.0, min(1.0, 1.0 - distance))

                result = SearchResult(
                    content=doc_text,
                    metadata=results["metadatas"][0][i] if results["metadatas"] else {},
                    score=score,
                    rank=i + 1,
                )
                search_results.append(result)

        # Deduplicate by content fingerprint
        if dedupe and search_results:
            search_results = deduplicate_results(search_results, top_k)

        logger.debug(
            "vectorstore.search",
            collection=collection_name,
            query_length=len(query),
            results=len(search_results),
        )

        return search_results

    async def delete_collection(self, collection_name: str) -> bool:
        """Delete a collection."""
        try:
            await asyncio.to_thread(
                self.client.delete_collection,
                name=collection_name,
            )
            logger.debug("vectorstore.delete_collection", collection=collection_name)
            return True
        except NotFoundError:
            return False

    async def list_collections(self) -> list[str]:
        """List all collection names."""
        collections = await asyncio.to_thread(self.client.list_collections)
        return [c.name for c in collections]

    async def get_collection_info(self, collection_name: str) -> CollectionInfo | None:
        """Get information about a collection including document count."""
        try:
            collection = await self._open(collection_name)
            count = await asyncio.to_thread(collection.count)

            # Get unique document count from metadata sources
            results = await asyncio.to_thread(collection.get, include=["metadatas"])
            unique_sources: set[str] = set()
            for meta in results.get("metadatas") or []:
                if meta and "source" in meta:
                    unique_sources.add(meta["source"])

            return CollectionInfo(
                name=collection_name,
                count=count,
                doc_count=len(unique_sources),
                metadata=collection.metadata or {},
            )
        except NotFoundError:
            return None

    async def collection_exists(self, collection_name: str) -> bool:
        """Check if a collection exists."""
        collections = await self.list_collections()
        return collection_name in collections
