"""The vector store tells a missing collection from a broken one.

chromadb 1.x saves a collection's embedding function in its config and
refuses to open it with another one (``ValueError``: "Embedding function
conflict"). Only ``NotFoundError`` means the collection is not there; a
conflict is a misconfiguration that has to surface, not an empty result.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from chromadb.errors import NotFoundError
import pytest

from app.services.rag.models import Document, Embedded, IndexedFile
from app.services.rag.vectorstore import VectorStoreManager


class _Client:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def get_collection(self, **_: Any) -> Any:
        raise self.error


async def _no_embedding() -> Any:
    """A model whose vector for a text is its length: what was embedded,
    by whom, without one."""
    return lambda texts: [[float(len(t)), 1.0] for t in texts]


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
    assert await manager.remove_by_source("docs", ["a.md"]) == 0


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

    metadata: dict[str, Any] = {}

    def __init__(self, metadatas: list[dict[str, Any]] | None = None) -> None:
        self.upserted: list[dict[str, Any]] = []
        self.metadatas = metadatas or []

    def upsert(self, **batch: Any) -> None:
        self.upserted.append(batch)

    def count(self) -> int:
        return len(self.metadatas)

    def get(self, **_: Any) -> dict[str, Any]:
        return {"ids": [], "metadatas": self.metadatas}


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


@pytest.mark.asyncio
async def test_embedding_and_storing_are_apart(tmp_path: Path) -> None:
    """One process embeds (a worker), another stores (the one writer): the
    vectors travel between them as plain JSON, and the store takes them as
    they are, embedding nothing itself."""
    collection = _Collection()
    store = _manager(tmp_path, _Holding(collection))
    chunks = [
        Document(content="alpha", metadata={"source": "a.md", "chunk_index": 0}),
        Document(content="be", metadata={"source": "a.md", "chunk_index": 1}),
    ]

    embedded = await store.embed(chunks)
    carried = Embedded.model_validate_json(embedded.model_dump_json())
    stats = await store.store(carried, "docs")

    (batch,) = collection.upserted
    assert batch["embeddings"] == [[5.0, 1.0], [2.0, 1.0]]
    assert batch["documents"] == ["alpha", "be"]
    assert batch["ids"] == stats.chunk_ids and len(set(stats.chunk_ids)) == 2
    assert stats.documents_added == 2


class _Opened:
    """A client that says how each collection was opened: with a model
    (search) or without one, and which it created."""

    def __init__(self, held: set[str]) -> None:
        self.held = held
        self.opened: list[tuple[str, bool]] = []
        self.created: list[str] = []

    def get_collection(self, name: str, **given: Any) -> _Collection:
        self.opened.append((name, "embedding_function" in given))
        if name not in self.held:
            raise NotFoundError(f"Collection {name} does not exist.")
        return _Collection([{"source": "a.md"}])

    def create_collection(self, name: str, **_: Any) -> _Collection:
        self.created.append(name)
        return _Collection()


@pytest.mark.asyncio
async def test_only_what_embeds_loads_the_model(tmp_path: Path) -> None:
    """Counting, listing, removing and storing vectors embedded already
    open a collection without the model, so a page that only reads never
    waits for it; making a collection records its model, so that loads it."""
    client = _Opened({"docs"})
    manager = _manager(tmp_path, client)
    loaded: list[bool] = []

    async def model() -> Any:
        loaded.append(True)
        return await _no_embedding()

    manager._embedding = model  # type: ignore[method-assign]
    vectors = Embedded(
        ids=["a"], texts=["a"], metadatas=[{"source": "a"}], vectors=[[1.0]]
    )

    await manager.get_collection_info("docs")
    await manager.list_indexed_files("docs")
    await manager.remove_by_source("docs", ["a.md"])
    await manager.store(vectors, "docs")
    assert loaded == [] and not any(with_model for _, with_model in client.opened)

    await manager.store(vectors, "new")
    assert client.created == ["new"] and loaded == [True]


@pytest.mark.asyncio
async def test_the_model_loads_once_off_the_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loading takes seconds: in a thread, so the server keeps answering,
    and once however many ask for it at the same time."""
    import threading

    from app.services.rag import vectorstore

    async def no_secret(_name: str) -> None:
        return None

    monkeypatch.setattr(vectorstore.secrets, "get", no_secret)
    manager = VectorStoreManager(persist_directory=str(tmp_path))
    built: list[int] = []

    def build(_key: str | None) -> Any:
        built.append(threading.get_ident())
        return object()

    monkeypatch.setattr(manager, "_create_embedding_function", build)

    first, second = await asyncio.gather(manager._embedding(), manager._embedding())

    assert first is second and len(built) == 1
    assert built[0] != threading.get_ident()


class _Shrunk:
    """A collection holding a file's three chunks, deleting what it is told."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    def get(self, **_: Any) -> dict[str, Any]:
        return {"ids": ["a:0", "a:1", "a:2"]}

    def delete(self, ids: list[str]) -> None:
        self.deleted += ids


@pytest.mark.asyncio
async def test_a_file_read_again_loses_only_the_chunks_it_no_longer_makes(
    tmp_path: Path,
) -> None:
    """Its new chunks are stored over the old ones (the same ids); only those
    past its new end go, not every chunk deleted and written back."""
    collection = _Shrunk()

    gone = await _manager(tmp_path, _Holding(collection)).remove_by_source(  # type: ignore[arg-type]
        "docs", ["a.md"], keep={"a:0", "a:1"}
    )

    assert collection.deleted == ["a:2"] and gone == 1
