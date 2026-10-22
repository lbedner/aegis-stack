"""The requests the server kept, as one typed read (``kept_requests``) for
the API, Illiana's ``requests`` tool and Overseer's replay: the recent
ones newest first, and one with its hops, named as the dry path names
them."""

from collections.abc import AsyncIterator

import pytest

from app.core import edges, replays, source_index
from app.core.ontology import Kind, current
from app.core.ontology.model import PartNode
from app.core.ontology.parts import node_of
from app.core.parts import Category
from app.core.replays import Hop
from app.core.tools import get_tool
from app.services.system import kept_requests, service_pieces, tools
from app.services.system.service_pieces import Piece
from tests._ontology import model_of
from tests._replays import kept

ROUTES = "app/components/backend/api/auth/router.py"
QUERIES = "app/services/auth/queries.py"
SHARED = "app/services/shared/deps.py"
DB = "component:database"


async def _id(path: str, *hops: Hop, route: str = "", status: int = 200) -> str:
    return (await kept(path, *hops, route=route, status=status)).id


@pytest.fixture(autouse=True)
async def fresh(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Auth (no sub-part of its own in the model) beside the Server and the
    Database; Auth opens up into its router and its queries."""
    await replays.reset()
    model = model_of(
        PartNode(kind=kind, name=name, category=Category.APP)
        for kind, name in (
            (Kind.COMPONENT, "backend"),
            (Kind.COMPONENT, "database"),
            (Kind.SERVICE, "auth"),
        )
    )
    monkeypatch.setattr(kept_requests, "current", lambda: model)
    pieces = [
        Piece("piece:router", "Router", "entry", (), (ROUTES,)),
        Piece("piece:queries", "Queries", "data", (), (QUERIES,)),
    ]
    monkeypatch.setattr(
        service_pieces,
        "held",
        lambda subject: pieces if subject == "service:auth" else [],
    )
    yield
    await replays.reset()


async def test_the_recent_requests_newest_first_and_by_route() -> None:
    await _id("/api/v1/users/1", route="/api/v1/users/{id}")
    await _id("/api/v1/me", Hop((edges.SERVER, DB), 1.0, 2.0, False, ()), status=401)
    await _id("/api/v1/users/2", route="/api/v1/users/{id}")
    newest = await kept_requests.recent()
    assert [r.path for r in newest] == [
        "/api/v1/users/2",
        "/api/v1/me",
        "/api/v1/users/1",
    ]
    assert (newest[1].status, newest[1].hop_count) == (401, 1)
    users = await kept_requests.recent(route="/api/v1/users/{id}", limit=1)
    assert [r.path for r in users] == ["/api/v1/users/2"]


async def test_a_request_reads_its_hops_in_start_order_named_as_the_dry_path() -> None:
    """A sub-part the model lacks (Auth's users) reads as its part, as the
    dry path names it; each line of code says the piece it is in."""
    late = Hop((edges.SERVER, "service:auth"), 0.0, 20.0, False, ((ROUTES, 9),))
    query = Hop(
        ("service:auth", "service:auth.users", DB),
        5.0,
        2.0,
        False,
        ((ROUTES, 9), (SHARED, 3), (QUERIES, 40)),
        ["user"],
    )
    request_id = await _id("/api/v1/me", query, late)
    found = await kept_requests.find(request_id)
    assert found is not None and found.hop_count == 2
    first, second = found.hops
    assert first.chain == (edges.SERVER, "service:auth")
    assert second.chain == ("service:auth", DB)
    assert second.tables == ("user",)
    router, shared, queries = second.lines
    assert router.piece is not None
    assert (router.piece.service, router.piece.title) == ("service:auth", "Router")
    assert (shared.path, shared.piece) == (SHARED, None)
    assert queries.piece is not None and queries.piece.key == "piece:queries"


async def test_a_request_not_kept_or_malformed_is_none() -> None:
    assert await kept_requests.find("0" * 32) is None
    assert await kept_requests.find("../etc") is None


async def test_illianas_tool_reads_what_the_api_does() -> None:
    """The same models, an admin's (the tool is granted as one): the recent
    ones, a route's, or one with its hops; an id not kept is said so."""
    request_id = await _id(
        "/api/v1/me", Hop((edges.SERVER, DB), 1.0, 2.0, False, ()), route="/me"
    )
    await _id("/api/v1/other")
    recent = [r.model_dump(mode="json") for r in await kept_requests.recent()]
    assert await tools.requests() == {"requests": recent, "kept": replays.KEEP}
    assert (await tools.requests(route="/me"))["requests"] == recent[1:]
    found = await kept_requests.find(request_id)
    assert found is not None
    assert await tools.requests(request_id=request_id) == {
        "request": found.model_dump(mode="json")
    }
    with pytest.raises(ValueError, match="kept"):
        await tools.requests(request_id="0" * 32)
    tool = get_tool("requests")
    assert tool is not None and tool.effect == "read" and tool.admin


def test_every_part_a_hop_names_reads_as_the_dry_path_names_it() -> None:
    """A hop names the part of each file its code ran in (``edges``); read
    (``kept_requests``), it is the node the dry path names for the same
    module (``node_of``), in every module of the app's."""
    index = source_index.project()
    ids = {node.id for node in current().nodes}
    named = {}
    for name, path in index.paths.items():
        dry = node_of(name, index, ids)
        hop = edges._owner(str(source_index.ROOT / path))
        if dry and hop and not hop.startswith("shared:"):
            named[name] = (kept_requests._named((hop,), ids), (dry,))
    assert named
    assert {name: pair for name, pair in named.items() if pair[0] != pair[1]} == {}
