"""The knowledge base's API (``/api/v1/rag``): a read is a signed-in
user's, a change (indexing, adding or removing a source, dropping a
collection) an admin's. An index call names a path on the server, so an
anonymous one must never reach it."""

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest

from app.services.rag.models import FileIndexResult
from app.services.rag.service import LoaderError
from app.services.shared.deps import Actor, get_admin_actor, get_owner_user_id
from app.services.system.patterns import dependency_names

READS = {"GET", "HEAD"}
# A search is posted (its query is a body) but changes nothing.
READ_POSTS = {"/api/v1/rag/search"}


def _routes(app: FastAPI) -> list[APIRoute]:
    return [
        r
        for r in app.routes
        if isinstance(r, APIRoute) and r.path.startswith("/api/v1/rag")
    ]


def test_every_rag_route_asks_who_is_calling(app: FastAPI) -> None:
    routes = _routes(app)
    assert routes
    unguarded = []
    for route in routes:
        read = route.methods <= READS or route.path in READ_POSTS
        wanted = get_owner_user_id if read else get_admin_actor
        if wanted.__name__ not in dependency_names(route):
            unguarded.append((sorted(route.methods), route.path))
    assert not unguarded, unguarded


class _Index:
    """The RAG service, with nothing embedded: what was added and removed."""

    def __init__(self, persist_directory: Path) -> None:
        self.config = SimpleNamespace(persist_directory=str(persist_directory))
        self.added: list[tuple[str, str]] = []
        self.removed: list[tuple[str, str]] = []

    async def add_file(self, path: str | Path, collection_name: str) -> FileIndexResult:
        if Path(path).name == "unreadable.bin":
            raise LoaderError(f"No content loaded from: {path}")
        self.added.append((str(path), collection_name))
        return FileIndexResult(
            file_path=str(path), file_hash="h", chunk_count=4, action="added"
        )

    async def remove_file(
        self, source_path: str, collection_name: str
    ) -> FileIndexResult:
        self.removed.append((source_path, collection_name))
        held = 0 if source_path.endswith("gone.md") else 4
        return FileIndexResult(
            file_path=source_path, file_hash="h", chunk_count=held, action="removed"
        )


@pytest.fixture
def index(
    app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[_Index]:
    from app.components.backend.api.rag import sources

    held = _Index(tmp_path / "chromadb")
    monkeypatch.setattr(sources, "get_rag_service", lambda: held)
    app.dependency_overrides[get_admin_actor] = lambda: Actor()
    yield held
    app.dependency_overrides.pop(get_admin_actor, None)


def test_an_uploaded_source_is_kept_and_indexed(
    client: TestClient, index: _Index, tmp_path: Path
) -> None:
    """Kept beside the index, so a reindex reads it again."""
    response = client.post(
        "/api/v1/rag/collections/default/sources",
        files={
            "file": ("refunds.md", b"# Refunds\n\nWithin 14 days.", "text/markdown")
        },
    )

    assert response.status_code == 200, response.text
    kept = tmp_path / "sources" / "default" / "refunds.md"
    assert kept.read_bytes() == b"# Refunds\n\nWithin 14 days."
    assert index.added == [(str(kept), "default")]
    assert response.json()["chunks"] == 4


def test_a_path_the_server_holds_is_indexed_as_it_is(
    client: TestClient, index: _Index
) -> None:
    response = client.post(
        "/api/v1/rag/collections/default/sources", data={"path": "/srv/docs/a.md"}
    )

    assert response.status_code == 200, response.text
    assert index.added == [("/srv/docs/a.md", "default")]


def test_an_upload_never_lands_outside_its_knowledge_base(
    client: TestClient, index: _Index, tmp_path: Path
) -> None:
    """A name that climbs, or names a drive, is kept by its last part, in
    its own folder; a collection that would climb is refused."""
    url = "/api/v1/rag/collections/{}/sources"
    climbing = ("../../etc/passwd", b"x", "text/plain")

    kept = client.post(url.format("default"), files={"file": climbing})
    refused = client.post(url.format("..escape"), files={"file": ("a.md", b"x")})
    a_drive = client.post(url.format("default"), files={"file": ("C:evil.md", b"x")})

    folder = tmp_path / "sources" / "default"
    assert kept.status_code == 200 and a_drive.status_code == 200
    assert refused.status_code == 400
    assert [path for path, _ in index.added] == [
        str(folder / "passwd"),
        str(folder / "evil.md"),
    ]


def test_an_upload_that_cannot_be_read_is_not_kept(
    client: TestClient, index: _Index, tmp_path: Path
) -> None:
    response = client.post(
        "/api/v1/rag/collections/default/sources",
        files={"file": ("unreadable.bin", b"\x00", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert not (tmp_path / "sources" / "default" / "unreadable.bin").exists()


def test_a_source_is_removed_and_one_not_held_is_not_found(
    client: TestClient, index: _Index
) -> None:
    url = "/api/v1/rag/collections/default/sources"

    assert client.delete(url, params={"source": "/srv/docs/a.md"}).status_code == 200
    assert client.delete(url, params={"source": "/srv/docs/gone.md"}).status_code == 404
    assert index.removed[0] == ("/srv/docs/a.md", "default")
