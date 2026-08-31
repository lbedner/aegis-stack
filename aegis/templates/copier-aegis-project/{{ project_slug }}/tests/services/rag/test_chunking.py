"""Tests for RAG document chunking."""

import pytest
from app.services.rag.chunking import DocumentChunker, estimate_chunks
from app.services.rag.models import Document


class TestDocumentChunker:
    """Tests for DocumentChunker."""

    @pytest.mark.asyncio
    async def test_chunk_small_document(self) -> None:
        """Test that small documents aren't chunked."""
        chunker = DocumentChunker(chunk_size=1000)
        docs = [Document(content="Small content", metadata={"source": "test"})]

        chunks = await chunker.chunk(docs)

        assert len(chunks) == 1
        assert chunks[0].content == "Small content"

    @pytest.mark.asyncio
    async def test_chunk_large_document(self) -> None:
        """Test chunking a large document."""
        chunker = DocumentChunker(chunk_size=100, chunk_overlap=20)
        large_content = "A" * 500
        docs = [Document(content=large_content, metadata={"source": "test"})]

        chunks = await chunker.chunk(docs)

        assert len(chunks) > 1
        # Check chunk metadata
        for chunk in chunks:
            assert "chunk_index" in chunk.metadata
            assert "total_chunks" in chunk.metadata

    @pytest.mark.asyncio
    async def test_preserves_metadata(self) -> None:
        """Test that original metadata is preserved in chunks."""
        chunker = DocumentChunker(chunk_size=50)
        docs = [
            Document(
                content="A" * 200,
                metadata={"source": "test.py", "language": "python"},
            )
        ]

        chunks = await chunker.chunk(docs)

        for chunk in chunks:
            assert chunk.metadata["source"] == "test.py"
            assert chunk.metadata["language"] == "python"

    @pytest.mark.asyncio
    async def test_chunk_overlap(self) -> None:
        """Test that chunks have overlap."""
        chunker = DocumentChunker(chunk_size=50, chunk_overlap=10)
        # Create content with distinct words
        content = "word1 word2 word3 word4 word5 word6 word7 word8 word9 word10"
        docs = [Document(content=content * 5, metadata={"source": "test"})]

        chunks = await chunker.chunk(docs)

        # Chunks should be created
        assert len(chunks) > 1

    @pytest.mark.asyncio
    async def test_empty_content(self) -> None:
        """Test handling empty content."""
        chunker = DocumentChunker(chunk_size=100)
        docs = [Document(content="", metadata={"source": "test"})]

        chunks = await chunker.chunk(docs)

        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_whitespace_only_content(self) -> None:
        """Test handling whitespace-only content."""
        chunker = DocumentChunker(chunk_size=100)
        docs = [Document(content="   \n\n   ", metadata={"source": "test"})]

        chunks = await chunker.chunk(docs)

        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_multiple_documents(self) -> None:
        """Test chunking multiple documents."""
        chunker = DocumentChunker(chunk_size=50)
        docs = [
            Document(content="A" * 100, metadata={"source": "file1.py"}),
            Document(content="B" * 100, metadata={"source": "file2.py"}),
        ]

        chunks = await chunker.chunk(docs)

        # Should have chunks from both documents
        sources = {c.metadata["source"] for c in chunks}
        assert "file1.py" in sources
        assert "file2.py" in sources


class TestChunkSizeValidation:
    """Non-positive sizes must fail loudly, not hang the splitter."""

    def test_zero_chunk_size_is_rejected_at_construction(self) -> None:
        with pytest.raises(ValueError, match="chunk_size"):
            DocumentChunker(chunk_size=0)

    @pytest.mark.asyncio
    async def test_zero_chunk_size_override_is_rejected(self) -> None:
        """``chunk_size=0`` used to silently fall back to the default;
        a negative value walked into a non-advancing split loop."""
        chunker = DocumentChunker(chunk_size=100)
        docs = [Document(content="A" * 200, metadata={"source": "test"})]

        with pytest.raises(ValueError, match="chunk_size"):
            await chunker.chunk(docs, chunk_size=0)

    def test_min_chunk_size_keeps_caller_intent(self) -> None:
        """The floor is only kept below the ceiling - it is not halved.
        Clamping 900 to 500 silently changed what the caller asked for."""
        chunker = DocumentChunker(chunk_size=1000, min_chunk_size=900)
        assert chunker.min_chunk_size == 900

    def test_min_chunk_size_never_reaches_the_ceiling(self) -> None:
        """A floor at or above the chunk size would filter every chunk."""
        chunker = DocumentChunker(chunk_size=1000, min_chunk_size=1000)
        assert chunker.min_chunk_size == 999


class TestEstimateChunks:
    """Tests for chunk estimation utility."""

    def test_estimate_single_chunk(self) -> None:
        """Test estimation for small content."""
        result = estimate_chunks(100, 1000, 200)
        assert result == 1

    def test_estimate_multiple_chunks(self) -> None:
        """Test estimation for large content."""
        # 1000 chars, 200 chunk size, 50 overlap = effective 150 per chunk
        result = estimate_chunks(1000, 200, 50)
        assert result > 1

    def test_estimate_zero_overlap(self) -> None:
        """Test estimation with no overlap."""
        result = estimate_chunks(1000, 200, 0)
        assert result == 5  # 1000 / 200

    def test_estimate_edge_case(self) -> None:
        """Test estimation edge cases."""
        # Content equal to chunk size
        result = estimate_chunks(100, 100, 0)
        assert result == 1
