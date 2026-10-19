"""The vector store tells a missing collection from a broken one.

chromadb 1.x saves a collection's embedding function in its config and
refuses to open it with another one (``ValueError``: "Embedding function
conflict"). Only ``NotFoundError`` means the collection is not there; a
conflict is a misconfiguration that has to surface, not an empty result.
"""

from pathlib import Path
from typing import Any

from chromadb.errors import NotFoundError
import pytest

from app.services.rag.vectorstore import VectorStoreManager


class _Client:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def get_collection(self, **_: Any) -> Any:
        raise self.error


async def _no_embedding() -> None:
    return None


def _manager(tmp_path: Path, error: Exception) -> VectorStoreManager:
    manager = VectorStoreManager(persist_directory=str(tmp_path))
    manager._client = _Client(error)  # type: ignore[assignment]
    manager._embedding = _no_embedding  # type: ignore[method-assign]
    return manager


@pytest.mark.asyncio
async def test_a_missing_collection_is_an_empty_result(tmp_path: Path) -> None:
    manager = _manager(tmp_path, NotFoundError("Collection docs does not exist."))
    assert await manager.search("q", "docs") == []
    assert await manager.get_collection_info("docs") is None
    assert await manager.remove_by_source("docs", "a.md") == 0


@pytest.mark.asyncio
async def test_an_embedding_conflict_surfaces(tmp_path: Path) -> None:
    conflict = ValueError("Embedding function conflict: new: openai vs persisted: st")
    manager = _manager(tmp_path, conflict)
    with pytest.raises(ValueError, match="Embedding function conflict"):
        await manager.search("q", "docs")
    with pytest.raises(ValueError, match="Embedding function conflict"):
        await manager.get_collection_info("docs")
