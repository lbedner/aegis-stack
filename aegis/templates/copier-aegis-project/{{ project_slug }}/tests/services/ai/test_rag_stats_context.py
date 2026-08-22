"""Tests for RAG stats context model."""

from app.services.ai.domains.chat.rag_stats_context import RAGStatsContext


class TestRAGStatsContext:
    """Test RAGStatsContext model and formatting."""

    def test_default_values(self) -> None:
        """Test default values for RAGStatsContext."""
        context = RAGStatsContext()

        assert context.enabled is False
        assert context.collection_count == 0
        assert context.collections == []
        assert context.embedding_model is None
        assert context.chunk_size is None
        assert context.chunk_overlap is None
        assert context.default_top_k is None
        assert context.last_activity is None

    def test_full_context_creation(self) -> None:
        """Test creating RAGStatsContext with all fields."""
        context = RAGStatsContext(
            enabled=True,
            collection_count=3,
            collections=[
                {"name": "my-code", "count": 1234},
                {"name": "docs", "count": 567},
                {"name": "default", "count": 89},
            ],
            embedding_model="text-embedding-3-small",
            chunk_size=1000,
            chunk_overlap=200,
            default_top_k=5,
            last_activity="2025-12-25T10:30:00",
        )

        assert context.enabled is True
        assert context.collection_count == 3
        assert len(context.collections) == 3
        assert context.embedding_model == "text-embedding-3-small"
        assert context.chunk_size == 1000
        assert context.chunk_overlap == 200
        assert context.default_top_k == 5
        assert context.last_activity == "2025-12-25T10:30:00"

    def test_format_for_prompt_disabled(self) -> None:
        """Test prompt formatting when RAG is disabled."""
        context = RAGStatsContext(enabled=False)
        output = context.format_for_prompt()

        assert output == "RAG: disabled"

    def test_format_for_prompt_enabled_basic(self) -> None:
        """Test prompt formatting with minimal data."""
        context = RAGStatsContext(
            enabled=True,
            collection_count=1,
        )
        output = context.format_for_prompt()

        assert "RAG: enabled" in output
        assert "1 collections" in output

    def test_format_for_prompt_with_collections(self) -> None:
        """Test prompt formatting with collections."""
        context = RAGStatsContext(
            enabled=True,
            collection_count=2,
            collections=[
                {"name": "my-code", "count": 1234},
                {"name": "docs", "count": 567},
            ],
            embedding_model="text-embedding-3-small",
        )
        output = context.format_for_prompt()

        assert "RAG: enabled" in output
        assert "2 collections" in output
        assert "embedding: text-embedding-3-small" in output
        assert "Collections:" in output
        assert "my-code (1,234 docs)" in output
        assert "docs (567 docs)" in output

    def test_format_for_prompt_with_config(self) -> None:
        """Test prompt formatting with config settings."""
        context = RAGStatsContext(
            enabled=True,
            collection_count=1,
            chunk_size=1000,
            chunk_overlap=200,
            default_top_k=5,
        )
        output = context.format_for_prompt()

        assert "Config:" in output
        assert "chunk_size=1000" in output
        assert "overlap=200" in output
        assert "top_k=5" in output

    def test_format_for_prompt_with_last_activity(self) -> None:
        """Test prompt formatting with last activity."""
        context = RAGStatsContext(
            enabled=True,
            collection_count=1,
            last_activity="2025-12-25T10:30:00",
        )
        output = context.format_for_prompt()

        assert "Last activity: 2025-12-25T10:30:00" in output

    def test_format_for_prompt_full(self) -> None:
        """Test prompt formatting with all data."""
        context = RAGStatsContext(
            enabled=True,
            collection_count=3,
            collections=[
                {"name": "my-code", "count": 1234},
                {"name": "docs", "count": 567},
                {"name": "default", "count": 89},
            ],
            embedding_model="text-embedding-3-small",
            chunk_size=1000,
            chunk_overlap=200,
            default_top_k=5,
            last_activity="2025-12-25T10:30:00",
        )
        output = context.format_for_prompt()

        # Check all sections present
        assert "RAG: enabled" in output
        assert "3 collections" in output
        assert "embedding: text-embedding-3-small" in output
        assert "Collections:" in output
        assert "Config:" in output
        assert "Last activity:" in output
        assert "Report these stats when asked about RAG" in output

    def test_to_metadata(self) -> None:
        """Test metadata conversion."""
        context = RAGStatsContext(
            enabled=True,
            collection_count=2,
            collections=[
                {"name": "my-code", "count": 1234},
                {"name": "docs", "count": 567},
            ],
            embedding_model="text-embedding-3-small",
        )
        metadata = context.to_metadata()

        assert metadata["enabled"] is True
        assert metadata["collection_count"] == 2
        assert metadata["collections"] == ["my-code", "docs"]
        assert metadata["embedding_model"] == "text-embedding-3-small"

    def test_to_metadata_empty(self) -> None:
        """Test metadata conversion with default values."""
        context = RAGStatsContext()
        metadata = context.to_metadata()

        assert metadata["enabled"] is False
        assert metadata["collection_count"] == 0
        assert metadata["collections"] == []
        assert metadata["embedding_model"] is None


class TestRAGStatsContextEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_collections_list(self) -> None:
        """Test with empty collections list."""
        context = RAGStatsContext(
            enabled=True,
            collection_count=0,
            collections=[],
        )
        output = context.format_for_prompt()

        assert "RAG: enabled" in output
        assert "0 collections" in output
        assert "Collections:" not in output

    def test_collection_with_zero_count(self) -> None:
        """Test collection with zero document count."""
        context = RAGStatsContext(
            enabled=True,
            collection_count=1,
            collections=[{"name": "empty", "count": 0}],
        )
        output = context.format_for_prompt()

        assert "empty (0 docs)" in output

    def test_large_document_count_formatting(self) -> None:
        """Test that large document counts are formatted with commas."""
        context = RAGStatsContext(
            enabled=True,
            collection_count=1,
            collections=[{"name": "big", "count": 1234567}],
        )
        output = context.format_for_prompt()

        assert "big (1,234,567 docs)" in output

    def test_partial_config(self) -> None:
        """Test with only some config values set."""
        context = RAGStatsContext(
            enabled=True,
            collection_count=1,
            chunk_size=1000,
            # chunk_overlap and default_top_k are None
        )
        output = context.format_for_prompt()

        assert "Config: chunk_size=1000" in output
        assert "overlap=" not in output
        assert "top_k=" not in output
