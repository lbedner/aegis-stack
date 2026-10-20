"""An app's own mount of the chat surface: who it serves and what about
are decided per request (``bind``: the signed-in user, the active
project), never by the browser; a turn may be refused before the model
(``gate``); and every turn streams through the mount's own route into the
one AI service."""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from app.components.backend.api.ai.service import ai_service
from app.components.web_frontend import chat_surface
from app.components.web_frontend.chat_surface import ChatSurface
from app.components.web_frontend.routes.partials.chat_surface import chat_router
from app.services.ai.models import (
    AIProvider,
    Conversation,
    ConversationMessage,
    MessageRole,
    StreamingMessage,
)
from tests.web.dom import one

MOUNT = ChatSurface(path="/chat", user="", surface="metrics", agent_slug="illiana")


def _conversation(conversation_id: str, user: str, subject: str) -> Conversation:
    return Conversation(
        id=conversation_id,
        provider=AIProvider.OLLAMA,
        model="m",
        metadata={"user_id": user, "surface": "metrics", "subject": subject},
        messages=[
            ConversationMessage(
                id="q1", role=MessageRole.USER, content=f"about {subject}?"
            ),
            ConversationMessage(id="a1", role=MessageRole.ASSISTANT, content="Yes."),
        ],
    )


STORED = {
    c.id: c
    for c in (
        _conversation("mine", "7", "3"),
        _conversation("other-project", "7", "4"),
        _conversation("other-user", "8", "3"),
    )
}


async def bind(request: Request) -> ChatSurface:
    """The signed-in user and the active project, as an app's own
    dependencies would say them (here, headers)."""
    return replace(
        MOUNT, user=request.headers["x-user"], subject=request.headers["x-project"]
    )


async def gate(request: Request) -> str | None:
    return "Over today's limit." if request.headers.get("x-spent") else None


async def allow() -> None:
    return None


@pytest.fixture
def turns(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every turn the AI service is asked to run, by its arguments."""
    asked: list[dict[str, Any]] = []

    async def stream_chat(**kwargs: Any) -> AsyncIterator[StreamingMessage]:
        asked.append(kwargs)
        yield StreamingMessage(
            content="Up 8%.",
            is_final=True,
            is_delta=False,
            message_id="a2",
            conversation_id="mine",
            timestamp=datetime.now(UTC),
        )

    async def get_conversation(conversation_id: str) -> Conversation | None:
        return STORED.get(conversation_id)

    async def list_conversations(
        user_id: str, surface: str | None = None, subject: str | None = None
    ) -> list[Conversation]:
        return [
            c
            for c in STORED.values()
            if (c.metadata["user_id"], c.metadata["subject"]) == (user_id, subject)
        ]

    async def assistant_name(chat: ChatSurface, session: object = None) -> str:
        return "Illiana"

    monkeypatch.setattr(ai_service, "stream_chat", stream_chat)
    monkeypatch.setattr(ai_service, "get_conversation", get_conversation)
    monkeypatch.setattr(ai_service, "list_conversations", list_conversations)
    monkeypatch.setattr(chat_surface, "assistant_name", assistant_name)
    return asked


@pytest.fixture
def client(turns: list[dict[str, Any]]) -> TestClient:
    # An app of its own: the shared one is session-wide, and a router
    # included there outlives the test.
    app = FastAPI()
    app.include_router(chat_router(replace(MOUNT, bind=bind, gate=gate), allow))
    return TestClient(app, headers={"x-user": "7", "x-project": "3"})


def _events(body: str) -> list[str]:
    return [b.split("\n")[0].removeprefix("event: ") for b in body.split("\n\n") if b]


def test_the_surface_opens_on_the_requests_own_conversations(
    client: TestClient,
) -> None:
    html = client.get("/chat/drawer").text
    assert "about 3?" in html
    assert one(html, "[name=conversation_id]").get("value") == "mine"
    # The page names only where it is: the turn's scope is not the
    # browser's to send.
    assert json.loads(one(html, "[data-chat]").get("data-chat")) == {"path": "/chat"}


def test_a_turn_runs_as_the_mount_says_whatever_the_body_claims(
    client: TestClient, turns: list[dict[str, Any]]
) -> None:
    body = {"message": "downloads?", "user_id": "8", "surface": "overseer"}
    response = client.post("/chat/stream", json=body)

    assert _events(response.text) == ["connect", "final", "complete"]
    (turn,) = turns
    assert (turn["user_id"], turn["subject"]) == ("7", "3")
    assert (turn["surface"], turn["agent_slug"]) == ("metrics", "illiana")


def test_a_turn_continues_only_the_mounts_own_conversation(
    client: TestClient, turns: list[dict[str, Any]]
) -> None:
    for other in ("other-project", "other-user", "missing"):
        body = {"message": "and now?", "conversation_id": other}
        assert client.post("/chat/stream", json=body).status_code == 404
    assert turns == []
    body = {"message": "and now?", "conversation_id": "mine"}
    assert client.post("/chat/stream", json=body).status_code == 200


def test_a_gated_turn_is_refused_before_the_model(
    client: TestClient, turns: list[dict[str, Any]]
) -> None:
    response = client.post(
        "/chat/stream", json={"message": "q"}, headers={"x-spent": "1"}
    )
    assert response.text == 'event: error\ndata: {"error": "Over today\'s limit."}\n\n'
    assert turns == []


def test_another_users_or_projects_conversation_is_absent(client: TestClient) -> None:
    assert client.get("/chat/conversations/mine").status_code == 200
    assert client.get("/chat/conversations/other-project").status_code == 404
    assert client.get("/chat/conversations/other-user").status_code == 404
    assert client.get("/chat/messages/other-user/a1").status_code == 404


def test_a_mount_for_an_apps_users_has_no_operator_controls(
    turns: list[dict[str, Any]],
) -> None:
    """The model and voice chips set what the whole install answers with,
    and a live call runs as the declared mount: an operator's. A mount for
    an app's own users turns them off, and then neither the chips, the
    call nor their routes exist. Speaking a turn and hearing one stay."""
    closed = replace(MOUNT, operator_controls=False)

    async def bind_closed(request: Request) -> ChatSurface:
        return replace(closed, user=request.headers["x-user"])

    app = FastAPI()
    app.include_router(chat_router(replace(closed, bind=bind_closed), allow))
    client = TestClient(app, headers={"x-user": "7", "x-project": "3"})

    drawer = client.get("/chat/drawer").text
    for absent in ('id="chat-model"', 'id="chat-voice"', 'id="chat-live"'):
        assert absent not in drawer
    assert client.get("/chat/models").status_code == 404
    assert client.post("/chat/models", data={"model_id": "m"}).status_code == 404
    assert client.get("/chat/voices").status_code == 404
    assert client.post("/chat/voices").status_code in (404, 405)
    if chat_surface.HAS_VOICE:
        assert 'id="chat-mic"' in drawer


def test_a_bound_mount_gives_its_operators_the_controls_and_no_one_else(
    turns: list[dict[str, Any]],
) -> None:
    """``bind`` decides per request: an operator's request gets the model
    and voice chips and their routes, anyone else's neither. A bound mount
    offers no live call to anyone (the call runs as the declared mount)."""

    async def bind_by_role(request: Request) -> ChatSurface:
        return replace(
            bound,
            user=request.headers["x-user"],
            operator_controls=request.headers.get("x-operator") == "yes",
        )

    bound = replace(MOUNT, bind=bind_by_role)
    app = FastAPI()
    app.include_router(chat_router(bound, allow))
    operator = TestClient(app, headers={"x-user": "1", "x-operator": "yes"})
    customer = TestClient(app, headers={"x-user": "7"})

    if chat_surface.PERSISTED:  # the model catalog is rows
        assert 'id="chat-model"' in operator.get("/chat/drawer").text
        assert operator.get("/chat/models").status_code == 200
    drawer = customer.get("/chat/drawer").text
    assert 'id="chat-model"' not in drawer and 'id="chat-voice"' not in drawer
    assert customer.get("/chat/models").status_code == 404
    assert customer.post("/chat/models", data={"model_id": "m"}).status_code == 404
    if chat_surface.HAS_VOICE:
        assert 'id="chat-voice"' in operator.get("/chat/drawer").text
        assert customer.get("/chat/voices").status_code == 404
        assert 'id="chat-live"' not in operator.get("/chat/drawer").text
