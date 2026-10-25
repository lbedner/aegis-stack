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
from app.components.web_frontend import overseer_replay
from app.components.web_frontend.overseer_ai_chat import OVERSEER
from app.core import edges, replays
from app.core.ontology.model import (
    EdgeKind,
    JobNode,
    Kind,
    PartNode,
    QueueNode,
    SystemModel,
    TaskNode,
)
from app.core.parts import Category
from app.core.replays import Hop
from app.services.ai.domains.chat.path_card import PathCard
from app.services.ai.models import AIProvider
from app.services.ai.models.chat_card import ChatCard
from app.services.system import kept_requests, staged_paths, topology
from app.services.system.kept_requests import RequestHops
from app.services.system.models import ComponentStatus
from tests._ontology import dry_walk, edge_of, model_of, node_of
from tests._replays import kept
from tests.web.dom import none, one, select, text
from tests.web.overseer import CACHE, page_html
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
    none(card, "[data-link][data-observed]")  # read from the code, not seen
    said = text(one(card, "[data-card=path]"))
    assert "Code path · GET /api/v1/auth/me · read from the code" in said


async def test_a_code_path_plays_each_way_through_the_map_once(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A code path reads function by function; on the map they fold onto
    a few parts, so a hop through parts an earlier one lit is that one
    again: it joins it (its table named there) rather than blinking the
    same line on and off (2026-10-24: "choppy as hell")."""
    client = zoomable(app, monkeypatch, INGRESS)
    auth_opens(monkeypatch)
    users = "service:auth.users"
    staged = _code_path(
        ("service:auth", DB), ("service:auth", users), (users, "object:user")
    )
    card_id = await _card(PathCard(title="Me", path=staged))
    steps = _steps(_opened(client, card_id))

    lit = [tuple(step["targets"]) for step in steps]
    assert len(lit) == len(set(lit))
    assert any("user" in str(step["says"]) for step in steps)


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


def _drawn(html: str) -> set[str]:
    return {str(n.get("data-node")) for n in select(html, "[data-node]")}


def _wired(monkeypatch: pytest.MonkeyPatch) -> None:
    """The model the ontology tool reads: Auth calls the database, the
    Server needs it, and Auth holds the user table and its sessions,
    which call Stripe."""
    sessions, stripe = "service:auth.sessions", "external:Stripe"
    job = JobNode(name="sweep", owner="service:auth", schedule="every 1h")
    model = model_of(
        [
            *(node_of(k) for k in ("service:auth", DB, edges.SERVER, sessions, stripe)),
            job,
        ],
        [
            edge_of("service:auth", "job:sweep", EdgeKind.CONTAINS),
            edge_of("service:auth", DB),
            edge_of(edges.SERVER, DB, EdgeKind.DEPENDS_ON),
            edge_of("service:auth", sessions, EdgeKind.CONTAINS),
            edge_of(sessions, stripe),
            # Seen both ways in traffic: the Server calls Auth, and back.
            edge_of(edges.SERVER, "service:auth"),
            edge_of("service:auth", edges.SERVER),
        ],
    )
    _serve(monkeypatch, model)


def _serve(monkeypatch: pytest.MonkeyPatch, model: SystemModel) -> None:
    """``model`` as the running one the cards read."""

    async def running() -> SystemModel:
        return model

    monkeypatch.setattr(overseer_replay, "running", running)


def test_a_queue_is_its_own_box_not_a_part_named_like_it() -> None:
    """The load test queue is drawn as itself, not on the load test
    service's box."""
    from app.services.system.staged_paths import registry_of

    assert registry_of("queue:load_test") == "queue:load_test"
    assert registry_of("task:cpu_task") == "task:cpu_task"
    assert registry_of("shared:load_test") == "load_test"


async def test_a_parts_wiring_draws_the_edges_she_read_and_nothing_else(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The edges the ontology tool answers for the database (whatever
    their kind, the Server outside the Server's map included), on the
    map; what nothing joins it to (Secrets) left off; still in the
    thread, nothing to play."""
    client = zoomable(app, monkeypatch, INGRESS)
    _wired(monkeypatch)
    card_id = await _card(PathCard(title="Database", node=DB))
    client.headers["HX-Request"] = "true"
    inline = client.get(f"{CARDS}/{card_id}").text

    assert _drawn(inline) == {"database", "service_auth", "backend"}
    none(inline, "[data-link][data-observed]")  # declared, not seen only
    assert "Wiring · Database" in text(one(inline, "[data-card=path]"))
    none(inline, "[data-play-badge]")


async def test_a_job_is_drawn_where_its_part_runs_it(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A job has no box on the map: its wiring is its part's, the lines
    the part that runs it is joined by (2026-10-24: the heartbeat's card
    drew the Scheduler alone)."""
    client = zoomable(app, monkeypatch, INGRESS)
    _wired(monkeypatch)
    card_id = await _card(PathCard(title="Sweep", node="job:sweep"))
    client.headers["HX-Request"] = "true"
    inline = client.get(f"{CARDS}/{card_id}").text

    assert {"service_auth", "database"} <= _drawn(inline)


def _queues(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis holds the queue, and in it the worker's two queues, each
    handing work to its tasks."""
    cache, queue = "component:cache", f"component:{topology.QUEUE}"
    queues = [QueueNode(name=q, owner=queue) for q in ("load_test", "system")]
    tasks = [
        TaskNode(name=name, queue=q, owner="component:worker")
        for q, name in (("load_test", "cpu_task"), ("load_test", "io_task"))
        + (("system", "health_task"),)
    ]
    model = model_of(
        [
            *(node_of(k) for k in (cache, "component:worker")),
            PartNode(
                kind=Kind.COMPONENT,
                name=topology.QUEUE,
                category=Category.DATA,
                owner=cache,
            ),
            *queues,
            *tasks,
        ],
        [
            edge_of(cache, queue, EdgeKind.CONTAINS),
            edge_of("component:worker", queue, EdgeKind.DEPENDS_ON),
            *(edge_of(queue, q.id, EdgeKind.CONTAINS) for q in queues),
            *(edge_of(f"queue:{t.queue}", t.id) for t in tasks),
        ],
    )
    _serve(monkeypatch, model)


WORKER = ComponentStatus(name="worker", message="Running", metadata={})


async def test_redis_wiring_draws_each_queue_and_its_tasks(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asked to draw Redis, then the workers and their tasks, she had boxes
    for the cache, the queue and the worker, and no task (2026-10-25):
    each queue it holds is a box under the queue, its tasks under it."""
    client = zoomable(app, monkeypatch, INGRESS, CACHE, WORKER)
    _queues(monkeypatch)
    card_id = await _card(PathCard(title="Redis", node="component:cache"))
    client.headers["HX-Request"] = "true"
    inline = client.get(f"{CARDS}/{card_id}").text

    assert {
        "queue:load_test",
        "queue:system",
        "task:cpu_task",
        "task:io_task",
        "task:health_task",
    } <= _drawn(inline)
    one(inline, '[data-link][data-from="queue"][data-to="queue:load_test"]')
    one(inline, '[data-link][data-from="queue:load_test"][data-to="task:cpu_task"]')


async def test_a_queues_wiring_draws_its_own_tasks(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = zoomable(app, monkeypatch, INGRESS, CACHE, WORKER)
    _queues(monkeypatch)
    card_id = await _card(PathCard(title="Load test", node="queue:load_test"))
    drawn = _drawn(_opened(client, card_id))

    assert {"queue", "queue:load_test", "task:cpu_task", "task:io_task"} <= drawn
    assert "task:health_task" not in drawn


async def test_opened_larger_a_wiring_is_still_a_map(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A service's wiring: what it calls, and what the parts it holds
    call (its sessions, Stripe), opened larger with no player; a part
    joined to it both ways is drawn once, as its caller."""
    client = zoomable(app, monkeypatch, INGRESS)
    _wired(monkeypatch)
    card_id = await _card(PathCard(title="Auth", node="service:auth"))
    opened = _opened(client, card_id)

    assert _drawn(opened) == {"service_auth", "database", "outside:Stripe", "backend"}
    one(opened, '[data-link][data-from="backend"][data-to="service_auth"]')
    none(opened, '[data-link][data-from="service_auth"][data-to="backend"]')
    none(opened, "[data-player]")
