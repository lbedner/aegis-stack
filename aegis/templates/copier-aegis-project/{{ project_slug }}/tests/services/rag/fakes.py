"""The RAG service with nothing embedded, for adding and removing sources:
what was listed, loaded, cleared, indexed, removed and deleted, and the
files and folders it holds. ``install`` puts one where ``rag.sources``
and ``rag.embedding`` find their service."""

from pathlib import Path

import pytest

from app.services.rag import embedding, knowable, sources
from app.services.rag.config import RAGServiceConfig
from app.services.rag.models import (
    Document,
    Embedded,
    FileIndexResult,
    IndexedFile,
    IndexStats,
)
from app.services.rag.service import LoaderError

UNREADABLE = ("unreadable.bin", "moved.md")


class FakeIndex:
    def __init__(self, persist_directory: Path) -> None:
        self.config = RAGServiceConfig(persist_directory=str(persist_directory))
        self.vectorstore = self
        self.loader = self
        self.held: list[IndexedFile] = []  # what the index holds
        # What a server path loads as: each file's source, by path.
        self.folders: dict[str, list[str]] = {}
        # What was listed to read (a path, its types, what is left out), and
        # each file then read.
        self.listed: list[tuple[str, list[str] | None, list[str] | None]] = []
        self.loaded: list[str] = []
        self.cleared: list[tuple[str, list[str]]] = []
        self.indexed: list[tuple[list[str], str]] = []
        self.removed: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def files(
        self,
        path: str | Path,
        extensions: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> list[Path]:
        self.listed.append((str(path), extensions, exclude_patterns))
        if str(path) in self.folders:
            return [Path(f) for f in self.folders[str(path)]]
        if Path(path).is_file():
            return [Path(path)]
        raise FileNotFoundError(f"Path not found: {path}")

    async def load_documents(self, path: str | Path) -> list[Document]:
        self.loaded.append(str(path))
        if Path(path).name in UNREADABLE:
            raise LoaderError(f"No content loaded from: {path}")
        if Path(path).is_file() and not Path(path).stat().st_size:
            return []  # an empty file loads as nothing, as the loader's does
        return [Document(content="x", metadata={"source": str(path)})]

    async def remove_by_source(
        self, collection_name: str, sources: list[str], keep: object = ()
    ) -> int:
        self.cleared.append((collection_name, sources))
        return len(sources)

    async def chunk_documents(self, documents: list[Document]) -> list[Document]:
        return documents + documents  # two chunks a file

    async def embed(self, documents: list[Document]) -> Embedded:
        return Embedded(
            ids=[f"{d.metadata['source']}:{n}" for n, d in enumerate(documents)],
            texts=[d.content for d in documents],
            metadatas=[d.metadata for d in documents],
            vectors=[[0.0]] * len(documents),
        )

    async def store(self, embedded: Embedded, collection_name: str) -> IndexStats:
        held = list(dict.fromkeys(m["source"] for m in embedded.metadatas))
        self.indexed.append((held, collection_name))
        return IndexStats(
            collection_name=collection_name,
            documents_added=len(embedded.ids),
            total_documents=len(embedded.ids),
            duration_ms=0,
        )

    async def remove_file(
        self, source_path: str, collection_name: str
    ) -> FileIndexResult:
        self.removed.append((source_path, collection_name))
        held = 0 if source_path.endswith("gone.md") else 4
        return FileIndexResult(
            file_path=source_path, file_hash="h", chunk_count=held, action="removed"
        )

    async def list_files(self, collection_name: str) -> list[IndexedFile]:
        return self.held

    async def delete_collection(self, collection_name: str) -> bool:
        self.deleted.append(collection_name)
        return True


def fake_paths_of(
    monkeypatch: pytest.MonkeyPatch, *found: str
) -> list[tuple[list[str], list[str]]]:
    """``knowable.paths_of`` answering ``found`` whatever is asked; what was
    asked (parts, types) recorded."""
    asked: list[tuple[list[str], list[str]]] = []

    def paths_of(
        parts: list[str], types: list[str], exclude: list[str] | None = None
    ) -> list[str]:
        asked.append((list(parts), list(types)))
        return list(found)

    monkeypatch.setattr(knowable, "paths_of", paths_of)
    return asked


@pytest.fixture(name="index")
def index_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeIndex:
    """A fake index in place of the RAG service (``install``)."""
    return install(tmp_path, monkeypatch)


def install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeIndex:
    """A fake index, its persist directory under ``tmp_path``, in place of
    the RAG service ``rag.sources`` reads; no worker, so it embeds here."""
    held = FakeIndex(tmp_path / "chromadb")
    monkeypatch.setattr(sources, "get_rag_service", lambda: held)
    monkeypatch.setattr(embedding, "get_rag_service", lambda: held)
    monkeypatch.setattr(embedding, "workers", lambda: False)
    return held
