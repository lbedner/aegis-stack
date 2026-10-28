"""The knowledge base's API (``/api/v1/rag``): a read is a signed-in
user's, a change (indexing, adding or removing a source, dropping a
collection) an admin's. An index call names a path on the server, so an
anonymous one must never reach it."""

from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest

from app.services.shared.deps import Actor, get_admin_actor, get_owner_user_id
from app.services.system.patterns import dependency_names
from tests.services.rag.fakes import FakeIndex, fake_paths_of

READS = {"GET", "HEAD"}
# A search is posted (its query is a body) but changes nothing.
READ_POSTS = {"/api/v1/rag/search"}
# What can be added names the server's folder and its files: an admin's.
ADMIN_READS = {"/api/v1/rag/knowable"}


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
        read = (route.methods <= READS or route.path in READ_POSTS) and (
            route.path not in ADMIN_READS
        )
        wanted = get_owner_user_id if read else get_admin_actor
        if wanted.__name__ not in dependency_names(route):
            unguarded.append((sorted(route.methods), route.path))
    assert not unguarded, unguarded


@pytest.fixture
def index(
    index: FakeIndex, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> Iterator[FakeIndex]:
    from app.components.backend.api.rag import sources

    monkeypatch.setattr(sources, "get_rag_service", lambda: index)
    app.dependency_overrides[get_admin_actor] = lambda: Actor()
    yield index
    app.dependency_overrides.pop(get_admin_actor, None)


def test_files_and_a_folder_are_added_as_rag_index_reads_them(
    client: TestClient, index: FakeIndex
) -> None:
    """What is kept, and where, is ``rag.sources``' (its own tests)."""
    index.folders["/srv/docs"] = ["/srv/docs/a.md"]

    response = client.post(
        "/api/v1/rag/collections/default/sources",
        files=[("file", ("refunds.md", b"14 days")), ("file", ("returns.md", b"x"))],
        data={"path": "/srv/docs", "extensions": "md, py", "exclude": "**/drafts/*"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "collection_name": "default",
        "files": 3,
        "chunks": 6,
        "unread": [],
    }
    assert index.listed[0] == ("/srv/docs", [".md", ".py"], ["**/drafts/*"])


def test_parts_of_this_app_are_added_by_id(
    client: TestClient, index: FakeIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ids ``GET /rag/knowable`` lists, read for the types asked."""
    asked = fake_paths_of(monkeypatch, "/code/app/services/ai/chat.py")

    response = client.post(
        "/api/v1/rag/collections/default/sources",
        data={"part": ["service:ai", "docs"], "extensions": "py"},
    )

    assert response.status_code == 200, response.text
    assert asked == [(["service:ai", "docs"], [".py"])]


def test_what_this_app_offers_is_listed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, app: FastAPI
) -> None:
    from app.services.rag import knowable
    from app.services.rag.knowable import Knowable

    offered = Knowable(
        parts=[("Services", [("service:ai", "ai", "AI")])],
        types=[("Code", [".py"])],
        held={"service:ai": {".py": (3, 300)}},
        ticked=[".py"],
    )
    monkeypatch.setattr(knowable, "knowable", lambda: offered)
    app.dependency_overrides[get_admin_actor] = lambda: Actor()

    response = client.get("/api/v1/rag/knowable")

    app.dependency_overrides.pop(get_admin_actor, None)
    assert response.status_code == 200, response.text
    assert response.json()["held"] == {"service:ai": {".py": [3, 300]}}


def test_what_cannot_be_added_is_a_bad_request(
    client: TestClient, index: FakeIndex
) -> None:
    """A collection that would climb, nothing readable, or nothing sent."""
    url = "/api/v1/rag/collections/{}/sources"

    refused = [
        client.post(url.format("..escape"), files={"file": ("a.md", b"x")}),
        client.post(url.format("default"), files={"file": ("unreadable.bin", b"\0")}),
        client.post(url.format("default"), data={"path": "/srv/missing"}),
        client.post(url.format("default")),
    ]

    assert [r.status_code for r in refused] == [400] * 4
    assert index.indexed == []


def test_a_name_the_index_cannot_take_is_refused_before_reading(
    client: TestClient, index: FakeIndex
) -> None:
    """``/rag/index`` too: a 400 at once, not a 500 once all is embedded."""
    response = client.post(
        "/api/v1/rag/index", json={"path": "/srv/docs", "collection_name": "Two Words"}
    )

    assert response.status_code == 400 and "no spaces" in response.json()["detail"]


def test_a_source_is_removed_and_one_not_held_is_not_found(
    client: TestClient, index: FakeIndex
) -> None:
    url = "/api/v1/rag/collections/default/sources"

    assert client.delete(url, params={"source": "/srv/docs/a.md"}).status_code == 200
    assert client.delete(url, params={"source": "/srv/docs/gone.md"}).status_code == 404
    assert index.removed[0] == ("/srv/docs/a.md", "default")


def test_a_collection_is_reindexed_whole_or_one_source_it_holds(
    client: TestClient, index: FakeIndex
) -> None:
    """Every source read again, or one; a path it does not hold is refused,
    never read in."""
    from app.services.rag.models import IndexedFile

    index.held = [
        IndexedFile(source="/srv/docs/a.md", chunks=2),
        IndexedFile(source="/srv/docs/b.md", chunks=1),
    ]
    url = "/api/v1/rag/collections/default/reindex"

    assert client.post(url).json()["files"] == 2
    assert client.post(url, params={"source": "/srv/docs/a.md"}).json()["files"] == 1
    refused = client.post(url, params={"source": "/etc/hosts"})
    assert refused.status_code == 400
    assert [held for held, _ in index.indexed] == [
        ["/srv/docs/a.md", "/srv/docs/b.md"],
        ["/srv/docs/a.md"],
    ]
