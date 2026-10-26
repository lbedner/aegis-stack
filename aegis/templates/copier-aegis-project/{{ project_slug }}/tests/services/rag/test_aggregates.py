"""What the knowledge index holds, as figures (``rag.collections``): each
collection's chunks and files, read from the vector store, never a chunk."""

import pytest

from app.services.rag import aggregates
from app.services.rag.models import CollectionInfo


async def test_each_collection_counts_its_chunks_and_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def stats() -> list[CollectionInfo]:
        return [
            CollectionInfo(name="docs", count=120, doc_count=4),
            CollectionInfo(name="code", count=30, doc_count=2),
        ]

    monkeypatch.setattr(aggregates, "collection_stats", stats)

    found = await aggregates.collections(None, None)

    assert found.chunks == {"docs": 120, "code": 30}
    assert found.files == {"docs": 4, "code": 2}
