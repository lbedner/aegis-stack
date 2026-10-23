"""A path card in the thread (``path_card``): a flow on the map, played by
the replay's own player from the replay's own steps, so a card and the
Replay page never tell one request two ways. Drawn once, no stream; the
map inert; a still thumbnail in the thread, played opened larger."""

from collections.abc import AsyncIterator
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.backend.api.ai.service import ai_service
from app.components.web_frontend.overseer_ai_chat import OVERSEER
from app.core import edges, replays
from app.core.replays import Hop
from app.services.ai.domains.chat.path_card import PathCard
from app.services.ai.models import AIProvider
from app.services.ai.models.chat_card import ChatCard
from app.services.system import kept_requests, staged_paths
from app.services.system.kept_requests import RequestHops
from app.services.system.models import ComponentStatus
from tests._ontology import dry_walk, edge_of, model_of, node_of
from tests._replays import kept
from tests.web.dom import none, one, text
from tests.web.overseer import page_html
from tests.web.zoomed import DB, auth_opens, zoomable

CARDS = f"{OVERSEER.path}/cards"
INGRESS = ComponentStatus(name="ingress", message="Routing", metadata={})
ROUTES = "app/components/backend/api/auth/router.py"


@pytest.fixture(autouse=True)
async def fresh() -> AsyncIterator[None]:
    await replays.reset()
    yield
    await replays.reset()


async def _card(card: PathCard) -> str:
    """A path card drawn in the Overseer chat's conversation, stored as the
    app stores one."""
    from app.core.db import get_async_session

    conversation = await ai_service.conversation_manager.create_conversation(
        provider=AIProvider.OLLAMA,
        model="gpt-6-luna",
        user_id=OVERSEER.user,
        surface=OVERSEER.surface,
    )
    await ai_service.conversation_manager.save_conversation(conversation)
    async with get_async_session() as session:
        row = ChatCard(
            conversation_id=conversation.id,
            kind="path",
            payload=card.model_dump(mode="json"),
        )
        session.add(row)
        return row.id


def _code_path(*edges_: tuple[str, str]) -> RequestHops:
    """``GET /api/v1/auth/me``'s code path, entered at Auth, through
    ``edges_``: no lines, so no pieces."""
    return staged_paths.dry(dry_walk("GET /api/v1/auth/me", "service:auth", *edges_))


def _opened(client: TestClient, card_id: str) -> str:
    """The card opened larger, where it plays."""
    client.headers["HX-Request"] = "true"
    return client.get(f"{CARDS}/{card_id}?size=large").text


def _steps(html: str) -> list[dict[str, object]]:
    steps: list[dict[str, object]] = json.loads(text(one(html, "[data-play-steps]")))
    return steps


async def test_a_kept_request_plays_as_its_replay_page_plays_it(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = zoomable(app, monkeypatch, INGRESS)
    auth_opens(monkeypatch)
    route = Hop((edges.SERVER, "service:auth"), 0.0, 20.0, False, ((ROUTES, 9),))
    query = Hop(("service:auth", DB), 5.0, 2.0, False, ((ROUTES, 9),), ["user"])
    found = await kept("/api/v1/auth/me", route, query)
    hops = await kept_requests.find(found.id)
    assert hops is not None
    card_id = await _card(PathCard(title="Who am I", path=hops))

    replayed = page_html(client, f"/overseer/replay/{found.id}")
    card = _opened(client, card_id)

    said = text(one(card, "[data-card=path]"))
    assert "Who am I" in said and "Replay · GET /api/v1/auth/me" in said
    assert _steps(card) == _steps(replayed)
    assert one(card, "[data-play-scene] [data-scene-map]").get("inert") is not None
    none(card, "[sse-connect]")


async def test_a_staged_path_says_what_it_went_through_not_how_long(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A beat a hop is no timing of the app's: no step claims a length."""
    client = zoomable(app, monkeypatch, INGRESS)
    auth_opens(monkeypatch)
    staged = _code_path(("service:auth", DB))
    card_id = await _card(PathCard(title="Me", path=staged))
    card = _opened(client, card_id)

    steps = _steps(card)
    assert steps and not any(" ms" in str(step["says"]) for step in steps)
    said = text(one(card, "[data-card=path]"))
    assert "Code path · GET /api/v1/auth/me · read from the code" in said


async def test_a_flow_with_nothing_inside_a_service_is_one_scene(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A service opens up only to show its pieces: a code path that went
    past Auth but through none of its pieces (no lines) plays on one map,
    not the Server's then an empty Auth's."""
    client = zoomable(app, monkeypatch, INGRESS)
    auth_opens(monkeypatch)
    staged = _code_path(("service:auth", DB), (DB, "external:Stripe"))
    card_id = await _card(PathCard(title="Paying", path=staged))
    card = _opened(client, card_id)

    one(card, "[data-play-scene]")
    none(card, "[data-play-chapter]")


async def test_in_the_thread_it_is_a_thumbnail_and_plays_opened_larger(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In the thread a flow is a still thumbnail of its map, marked to
    play: no player running under the chat (opened larger, it plays:
    ``test_a_kept_request_plays_as_its_replay_page_plays_it``)."""
    client = zoomable(app, monkeypatch, INGRESS)
    auth_opens(monkeypatch)
    card_id = await _card(PathCard(title="Me", path=_code_path(("service:auth", DB))))
    client.headers["HX-Request"] = "true"
    inline = client.get(f"{CARDS}/{card_id}").text

    assert "Me" in text(one(inline, "[data-card=path]"))
    assert one(inline, "[data-thumb] [data-scene-map]").get("inert") is not None
    one(inline, "[data-thumb] [data-play-badge]")
    none(inline, "[data-player]")


def _flow(*stops: str) -> RequestHops:
    """A flow through ``stops``, Auth calling the database."""
    model = model_of(
        [node_of("service:auth"), node_of(DB)], [edge_of("service:auth", DB)]
    )
    return staged_paths.joined(model, stops)


async def test_a_flow_not_entered_through_the_server_has_no_way_in(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The way in (the ingress, the Server) leads a path that starts at the
    Server; a flow starting elsewhere starts where it starts."""
    client = zoomable(app, monkeypatch, INGRESS)
    auth_opens(monkeypatch)
    staged = _flow("service:auth", DB)
    card_id = await _card(PathCard(title="Reading", path=staged))
    card = _opened(client, card_id)

    none(card, '[data-node="ingress"]')
    assert _steps(card)[0]["at"] == 0.0
    assert "Flow · along the map's lines" in text(one(card, "[data-card=path]"))
