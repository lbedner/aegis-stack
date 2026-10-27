"""The vector store tells a missing collection from a broken one.

chromadb 1.x saves a collection's embedding function in its config and
refuses to open it with another one (``ValueError``: "Embedding function
conflict"). Only ``NotFoundError`` means the collection is not there; a
conflict is a misconfiguration that has to surface, not an empty result.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from chromadb.errors import NotFoundError
import pytest

from app.services.rag.models import Document, IndexedFile
from app.services.rag.vectorstore import VectorStoreManager


class _Client:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def get_collection(self, **_: Any) -> Any:
        raise self.error


async def _no_embedding() -> None:
    return None


def _manager(tmp_path: Path, client: Any) -> VectorStoreManager:
    manager = VectorStoreManager(persist_directory=str(tmp_path))
    manager._client = client
    manager._embedding = _no_embedding  # type: ignore[method-assign]
    return manager


@pytest.mark.asyncio
async def test_a_missing_collection_is_an_empty_result(tmp_path: Path) -> None:
    missing = NotFoundError("Collection docs does not exist.")
    manager = _manager(tmp_path, _Client(missing))
    assert await manager.search("q", "docs") == []
    assert await manager.get_collection_info("docs") is None
    assert await manager.remove_by_source("docs", "a.md") == 0


@pytest.mark.asyncio
async def test_an_embedding_conflict_surfaces(tmp_path: Path) -> None:
    conflict = ValueError("Embedding function conflict: new: openai vs persisted: st")
    manager = _manager(tmp_path, _Client(conflict))
    with pytest.raises(ValueError, match="Embedding function conflict"):
        await manager.search("q", "docs")
    with pytest.raises(ValueError, match="Embedding function conflict"):
        await manager.get_collection_info("docs")


class _Collection:
    """A collection that keeps what it was given."""

    def __init__(self, metadatas: list[dict[str, Any]] | None = None) -> None:
        self.upserted: list[dict[str, Any]] = []
        self.metadatas = metadatas or []

    def upsert(self, **batch: Any) -> None:
        self.upserted.append(batch)

    def count(self) -> int:
        return len(self.metadatas)

    def get(self, **_: Any) -> dict[str, Any]:
        return {"metadatas": self.metadatas}


class _Holding:
    def __init__(self, collection: _Collection) -> None:
        self.collection = collection

    def get_or_create_collection(self, **_: Any) -> _Collection:
        return self.collection

    def get_collection(self, **_: Any) -> _Collection:
        return self.collection


@pytest.mark.asyncio
async def test_each_chunk_says_when_it_was_indexed(tmp_path: Path) -> None:
    """What the index holds and since when is the index's own: the
    knowledge base's records are read from it."""
    collection = _Collection()
    chunk = Document(content="a", metadata={"source": "a.md", "chunk_index": 0})

    await _manager(tmp_path, _Holding(collection)).add_documents([chunk], "docs")

    (batch,) = collection.upserted
    assert datetime.fromisoformat(batch["metadatas"][0]["indexed_at"])


@pytest.mark.asyncio
async def test_a_file_lists_when_it_was_indexed_and_what_it_is(tmp_path: Path) -> None:
    earlier, later = "2026-10-26T10:00:00", "2026-10-27T10:00:00"
    collection = _Collection(
        [
            {"source": "a.md", "file_type": "documentation", "indexed_at": earlier},
            {"source": "a.md", "file_type": "documentation", "indexed_at": later},
            {"source": "b.py"},  # indexed before chunks said when
        ]
    )

    files = await _manager(tmp_path, _Holding(collection)).list_indexed_files("docs")

    assert files == [
        IndexedFile(
            source="a.md",
            chunks=2,
            indexed_at=datetime.fromisoformat(later),
            content_type="documentation",
        ),
        IndexedFile(source="b.py", chunks=1),
    ]
