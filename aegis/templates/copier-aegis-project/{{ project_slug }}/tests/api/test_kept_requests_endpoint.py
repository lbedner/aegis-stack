"""The requests the server kept (``GET /api/v1/requests``): the recent ones
newest first, and one with its hops; admins only, open on a stack without
auth, as every operator route is. Its own reads are not kept."""

from collections.abc import AsyncIterator

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.core import edges, replays
from app.core.replays import Hop
from app.services.shared.deps import get_admin_actor
from tests._audit import as_admin
from tests._replays import kept

URL = "/api/v1/requests"


@pytest.fixture(autouse=True)
async def fresh() -> AsyncIterator[None]:
    await replays.reset()
    yield
    await replays.reset()


async def _served(path: str, route: str, *hops: Hop) -> str:
    return (await kept(path, *hops, route=route, ms=8.0)).id


async def test_an_admin_reads_the_recent_requests_newest_first_by_route(
    client: TestClient,
) -> None:
    await _served("/api/v1/a", "/api/v1/a")
    await _served("/api/v1/b/1", "/api/v1/b/{id}")
    await _served("/api/v1/b/2", "/api/v1/b/{id}")
    admin = as_admin(client)
    every = admin.get(URL).json()
    assert [r["path"] for r in every] == ["/api/v1/b/2", "/api/v1/b/1", "/api/v1/a"]
    picked = admin.get(URL, params={"route": "/api/v1/b/{id}", "limit": 1}).json()
    assert [r["path"] for r in picked] == ["/api/v1/b/2"]
    # Reading them is not kept: it would crowd out the app's own.
    assert len(admin.get(URL).json()) == 3


async def test_one_request_reads_with_its_hops_in_start_order(
    client: TestClient,
) -> None:
    late = Hop((edges.SERVER, "component:database"), 6.0, 1.0, False, ())
    early = Hop((edges.SERVER, "component:database"), 1.0, 2.0, False, ())
    request_id = await _served("/api/v1/a", "/api/v1/a", late, early)
    found = as_admin(client).get(f"{URL}/{request_id}")
    assert found.status_code == 200
    assert [hop["at_ms"] for hop in found.json()["hops"]] == [1.0, 6.0]


def test_a_malformed_id_is_refused_and_an_unknown_one_not_found(
    client: TestClient,
) -> None:
    admin = as_admin(client)
    assert admin.get(f"{URL}/not-an-id").status_code == 422
    assert admin.get(f"{URL}/{'0' * 32}").status_code == 404


def test_anyone_else_is_refused(client: TestClient) -> None:
    def refused() -> None:
        raise HTTPException(status_code=403)

    client.app.dependency_overrides[get_admin_actor] = refused
    assert client.get(URL).status_code == 403
    assert client.get(f"{URL}/{'0' * 32}").status_code == 403
