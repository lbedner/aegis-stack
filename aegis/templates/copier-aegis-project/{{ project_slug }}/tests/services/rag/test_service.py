"""Tests for RAG service core functionality."""

from pathlib import Path

import pytest
from app.services.rag.config import RAGServiceConfig
from app.services.rag.service import LoaderError, RAGService


@pytest.fixture
def rag_service(tmp_path: Path) -> RAGService:
    """Create RAG service instance with temporary storage."""
    config = RAGServiceConfig(
        persist_directory=str(tmp_path / "chromadb"),
        chunk_size=500,
        chunk_overlap=100,
        default_top_k=3,
    )
    return RAGService(config)


@pytest.fixture
def sample_codebase(tmp_path: Path) -> Path:
    """Create sample files for testing."""
    code_dir = tmp_path / "code"
    code_dir.mkdir()

    (code_dir / "main.py").write_text("""
def calculate_sum(a: int, b: int) -> int:
    \"\"\"Calculate the sum of two numbers.\"\"\"
    return a + b

def main():
    result = calculate_sum(1, 2)
    print(f"Result: {result}")
""")
    (code_dir / "README.md").write_text("""
# Calculator Project

A simple calculator implementation in Python.

## Features
- Add two numbers
- Print results
""")
    return code_dir


class TestRAGService:
    """Tests for RAGService."""

    @pytest.mark.asyncio
    async def test_load_documents(
        self, rag_service: RAGService, sample_codebase: Path
    ) -> None:
        """Test loading documents."""
        docs = await rag_service.load_documents(sample_codebase)

        assert len(docs) == 2
        extensions = [d.metadata["extension"] for d in docs]
        assert ".py" in extensions
        assert ".md" in extensions

    @pytest.mark.asyncio
    async def test_load_documents_with_filter(
        self, rag_service: RAGService, sample_codebase: Path
    ) -> None:
        """Test loading with extension filter."""
        docs = await rag_service.load_documents(sample_codebase, extensions=[".py"])

        assert len(docs) == 1
        assert docs[0].metadata["extension"] == ".py"

    @pytest.mark.asyncio
    async def test_load_documents_nonexistent_path(
        self, rag_service: RAGService
    ) -> None:
        """Test loading from non-existent path raises error."""
        with pytest.raises(LoaderError):
            await rag_service.load_documents("/nonexistent/path")

    @pytest.mark.asyncio
    async def test_chunk_documents(
        self, rag_service: RAGService, sample_codebase: Path
    ) -> None:
        """Test chunking documents."""
        docs = await rag_service.load_documents(sample_codebase)
        chunks = await rag_service.chunk_documents(docs)

        assert len(chunks) >= len(docs)
        for chunk in chunks:
            assert "chunk_index" in chunk.metadata

    @pytest.mark.asyncio
    async def test_full_indexing_workflow(
        self, rag_service: RAGService, sample_codebase: Path
    ) -> None:
        """Test complete load -> chunk -> index workflow."""
        # Load documents
        docs = await rag_service.load_documents(sample_codebase)
        assert len(docs) == 2

        # Chunk documents
        chunks = await rag_service.chunk_documents(docs)
        assert len(chunks) >= 2

        # Index documents
        stats = await rag_service.index_documents(chunks, "test_codebase")
        assert stats.documents_added == len(chunks)

    @pytest.mark.asyncio
    async def test_refresh_index(
        self, rag_service: RAGService, sample_codebase: Path
    ) -> None:
        """Test refresh_index convenience method."""
        stats = await rag_service.refresh_index(sample_codebase, "refresh_test")

        assert stats.documents_added > 0
        assert stats.collection_name == "refresh_test"

    @pytest.mark.asyncio
    async def test_search_indexed_content(
        self, rag_service: RAGService, sample_codebase: Path
    ) -> None:
        """Test searching indexed content."""
        # Index codebase
        await rag_service.refresh_index(sample_codebase, "search_test")

        # Search for function
        results = await rag_service.search(
            "how to calculate sum", "search_test", top_k=3
        )

        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_collection_management(
        self, rag_service: RAGService, sample_codebase: Path
    ) -> None:
        """Test collection listing and deletion."""
        # Create a collection
        await rag_service.refresh_index(sample_codebase, "manage_test")

        # List collections
        collections = await rag_service.list_collections()
        assert "manage_test" in collections

        # Get stats
        stats = await rag_service.get_collection_stats("manage_test")
        assert stats is not None
        assert stats["count"] > 0  # Total chunks
        assert stats["doc_count"] > 0  # Unique documents

        # Delete collection
        deleted = await rag_service.delete_collection("manage_test")
        assert deleted

        # Verify deletion
        collections = await rag_service.list_collections()
        assert "manage_test" not in collections

    def test_service_status(self, rag_service: RAGService) -> None:
        """Test service status reporting."""
        status = rag_service.get_service_status()

        assert status["enabled"] is True
        assert "persist_directory" in status
        assert "chunk_size" in status

    def test_validate_service(self, rag_service: RAGService) -> None:
        """Test service validation."""
        errors = rag_service.validate_service()

        # Should have no errors with valid config
        assert len(errors) == 0
