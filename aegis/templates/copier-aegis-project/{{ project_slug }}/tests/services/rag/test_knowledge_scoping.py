"""Tests for chunking-strategy presets and agent-scoped search."""

from typing import Any

import pytest

from app.services.rag.chunking import CHUNKING_STRATEGIES, chunk_params_for_strategy
from app.services.rag.models import SearchResult
from app.services.rag.service import RAGService, SearchError


class TestChunkingStrategies:
    def test_all_strategies_have_params(self) -> None:
        assert set(CHUNKING_STRATEGIES) == {"paragraph", "sentence", "fixed", "code"}
        for size, overlap in CHUNKING_STRATEGIES.values():
            assert size > overlap >= 0

    def test_known_strategy_maps_to_its_params(self) -> None:
        assert chunk_params_for_strategy("fixed") == CHUNKING_STRATEGIES["fixed"]

    def test_unknown_strategy_falls_back_to_paragraph(self) -> None:
        assert (
            chunk_params_for_strategy("nonsense")
            == CHUNKING_STRATEGIES["paragraph"]
        )


def _result(source: str, score: float) -> SearchResult:
    return SearchResult(
        content=f"chunk from {source}",
        metadata={"source": source},
        score=score,
        rank=1,
    )


class MockSettings:
    """Minimal settings for RAGService construction."""

    RAG_ENABLED = True
    RAG_PERSIST_DIRECTORY = "./test_data/chromadb"
    RAG_EMBEDDING_PROVIDER = "sentence-transformers"
    RAG_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
    RAG_MODEL_CACHE_DIR = "./test_data/models"
    OPENAI_API_KEY = None
    RAG_CHUNK_SIZE = 500
    RAG_CHUNK_OVERLAP = 100
    RAG_DEFAULT_TOP_K = 3


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> RAGService:
    from app.services.rag.config import get_rag_config

    rag_service = RAGService(get_rag_config(MockSettings()))

    per_collection: dict[str, list[SearchResult]] = {
        "kb-food": [_result("food.md", 0.9), _result("food2.md", 0.5)],
        "kb-health": [_result("health.md", 0.7)],
    }

    async def fake_search(
        query: str,
        collection_name: str,
        top_k: int | None = None,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        if collection_name not in per_collection:
            raise SearchError(f"no such collection: {collection_name}")
        return per_collection[collection_name]

    monkeypatch.setattr(rag_service, "search", fake_search)
    return rag_service


class TestScopedSearch:
    async def test_scoped_search_merges_and_ranks_across_collections(
        self, service: RAGService
    ) -> None:
        results = await service.search_scoped(
            "query", allowed_collections=["kb-food", "kb-health"], top_k=2
        )

        # Merged across both collections, sorted by score, cut to top_k.
        assert [r.metadata["source"] for r in results] == ["food.md", "health.md"]

    async def test_scoped_search_only_touches_allowed_collections(
        self, service: RAGService
    ) -> None:
        results = await service.search_scoped(
            "query", allowed_collections=["kb-health"], top_k=5
        )

        assert [r.metadata["source"] for r in results] == ["health.md"]

    async def test_missing_collection_is_skipped_not_fatal(
        self, service: RAGService
    ) -> None:
        results = await service.search_scoped(
            "query", allowed_collections=["kb-ghost", "kb-health"], top_k=5
        )

        assert [r.metadata["source"] for r in results] == ["health.md"]
