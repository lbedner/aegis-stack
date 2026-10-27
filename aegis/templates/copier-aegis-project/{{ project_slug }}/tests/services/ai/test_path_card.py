"""The path card (``path_card``): a flow on the map, drawn under an answer
and played. She names its source (a kept request, a route,
or a flow's stops); the server stages it as hops, once, when it is drawn,
so the card plays after the request is no longer kept."""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.ontology.model import ContainerNode, EdgeKind, SystemModel
from app.core.tools import acting_as, result_data
from app.services.ai.domains.chat import cards, path_card
from app.services.ai.domains.chat.cards import card_stage, draw_card
from app.services.ai.domains.chat.path_card import PathAsk, PathCard
from app.services.ai.domains.chat.user_memory import memory_user
from app.services.ai.models.chat_card import ChatCard
from app.services.system.kept_requests import RequestHops
from tests._ontology import edge_of, model_of, node_of
from tests._session import opens

KEPT = RequestHops(
    id="a" * 32,
    method="GET",
    path="/api/v1/auth/me",
    route="/api/v1/auth/me",
    status=200,
    ms=27.0,
    hop_count=0,
    dropped=0,
    hops=(),
)


@pytest.fixture(autouse=True)
def admin() -> Iterator[None]:
    with acting_as(None, None, admin=True):
        yield


async def test_a_kept_request_is_kept_in_the_card_as_it_ran(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def find(request_id: str) -> RequestHops | None:
        return KEPT if request_id == KEPT.id else None

    monkeypatch.setattr(path_card.kept_requests, "find", find)
    card = await path_card.prepare(PathAsk(title="Who am I", request_id=KEPT.id))
    assert card == PathCard(title="Who am I", path=KEPT)
    with pytest.raises(ValueError, match="no longer kept"):
        await path_card.prepare(PathAsk(title="x", request_id="b" * 32))


async def test_a_flows_stops_are_joined_on_the_running_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Joined along what runs now (traffic seen among it), never guessed."""
    auth, db = "service:auth", "component:database"
    model = model_of([node_of(auth), node_of(db)], [edge_of(auth, db)])

    async def running() -> SystemModel:
        return model

    monkeypatch.setattr(path_card, "running", running)
    card = await path_card.prepare(PathAsk(title="Reading", stops=[auth, db]))
    assert card.path.staged and [h.chain for h in card.path.hops] == [(auth, db)]
    with pytest.raises(ValueError, match="Nothing on the map"):
        await path_card.prepare(PathAsk(title="x", stops=[db, auth]))


async def test_a_nodes_wiring_names_a_node_the_running_model_has(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drawn from the map when opened, so kept as the node alone; a node
    the model does not have is refused by name."""
    auth, db = "service:auth", "component:database"

    async def running() -> SystemModel:
        return model_of([node_of(auth), node_of(db)], [edge_of(auth, db)])

    monkeypatch.setattr(path_card, "running", running)
    card = await path_card.prepare(PathAsk(title="Auth", node=auth))
    assert card == PathCard(title="Auth", node=auth)
    with pytest.raises(ValueError, match="service:auths"):
        await path_card.prepare(PathAsk(title="x", node="service:auths"))


async def test_a_wiring_with_nothing_on_the_map_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drawn on the parts it is joined to: the load test service runs in a
    container, no box on the map, and its card was drawn empty
    (2026-10-25)."""
    shared, box = "shared:load_test", "container:webserver"
    model = model_of(
        [node_of(shared), ContainerNode(name="webserver")],
        [edge_of(shared, box, EdgeKind.RUNS_ON)],
    )

    async def running() -> SystemModel:
        return model

    monkeypatch.setattr(path_card, "running", running)
    with pytest.raises(ValueError, match="Nothing on the map"):
        await path_card.prepare(PathAsk(title="Load test", node=shared))


async def test_a_route_is_its_dry_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def route(key: str) -> RequestHops:
        assert key == "GET /api/v1/auth/me"
        return KEPT

    monkeypatch.setattr(path_card.staged_paths, "route", route)
    card = await path_card.prepare(PathAsk(title="Me", route="GET /api/v1/auth/me"))
    assert card.path == KEPT


@pytest.mark.parametrize(
    ("sources", "got"),
    [
        ({}, "got none"),
        ({"request_id": "a" * 32, "route": "GET /x"}, "got request_id, route"),
        ({"route": "GET /x", "stops": ["a", "b"]}, "got route, stops"),
    ],
)
def test_a_card_names_exactly_one_source(sources: dict[str, Any], got: str) -> None:
    """The refusal says what was given and what each source is for, so the
    next call is the right one, not another guess."""
    with pytest.raises(ValueError, match="one of") as refused:
        PathAsk(title="x", **sources)
    assert got in str(refused.value)
    assert "drawn for you" in str(refused.value)


async def test_only_an_admin_draws_one() -> None:
    """A request's path is the app's code and traffic: an admin's."""
    with acting_as(None, None, admin=False), pytest.raises(ValueError, match="admin"):
        await path_card.prepare(PathAsk(title="x", route="GET /x"))


async def test_drawn_it_is_stored_staged_and_says_why_when_it_cannot_be(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``draw_card("path", ...)`` stores what was staged, not what she
    asked for; a source that cannot be staged is a tool error she can fix."""
    monkeypatch.setattr(cards, "get_async_session", opens(async_db_session))

    async def route(key: str) -> RequestHops:
        if key != "GET /me":
            raise ValueError(f"No route {key!r}")
        return KEPT

    monkeypatch.setattr(path_card.staged_paths, "route", route)
    with memory_user("0", conversation_id="conv-1", admin=True), card_stage():
        drawn = result_data(await draw_card("path", {"title": "Me", "route": "GET /me"}))
        refused = result_data(await draw_card("path", {"title": "x", "route": "GET /nope"}))
    stored = await async_db_session.get(ChatCard, drawn["id"])
    assert stored is not None and stored.payload["path"]["path"] == KEPT.path
    assert "GET /nope" in refused["error"]
