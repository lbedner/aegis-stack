"""The JSON chat API (``backend/api/ai/chat.py``, ``cards.py``,
``speech.py``) is a member's own: with sign-in on, whose turn, history and
cards these are comes from the session, never from a ``user_id`` the
client sends. A signed-in user naming another reaches only their own;
nobody signed in, and no guest (``auth[guest]``, a visitor, never a user),
reaches it at all."""

from collections.abc import AsyncIterator
from importlib.util import find_spec
from typing import Any

from fastapi.testclient import TestClient
import pytest

from app.components.backend.api.ai.service import ai_service
from app.core.config import settings
from app.services.ai.models import (
    AIProvider,
    Conversation,
    ConversationMessage,
    MessageRole,
)

# Without auth there is no session to read a user from: one user without sign-in.
bearer = pytest.importorskip("tests._bearer").bearer
MEMBER = bearer("owner2@test.local")
HAS_VOICE = find_spec("app.components.backend.api.ai.speech") is not None
HAS_CARDS = find_spec("app.services.ai.domains.chat.cards") is not None


@pytest.fixture(autouse=True)
def _auth_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)


def _theirs() -> Conversation:
    return Conversation(
        id="theirs",
        provider=AIProvider.OLLAMA,
        model="m",
        metadata={"user_id": "7"},
        messages=[ConversationMessage(id="q", role=MessageRole.USER, content="mine")],
    )


def test_a_list_is_the_callers_own(
    async_client_with_db: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str | None] = []

    async def list_conversations(user_id: str | None = None, **_: Any) -> list[Any]:
        asked.append(user_id)
        return []

    monkeypatch.setattr(ai_service, "list_conversations", list_conversations)
    response = async_client_with_db.get(
        "/api/v1/ai/conversations", params={"user_id": "7"}, headers=MEMBER
    )
    assert response.status_code == 200, response.text
    assert asked == ["2"]


def test_another_users_conversation_is_not_read(
    async_client_with_db: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def get_conversation(
        conversation_id: str, user_id: str | None = None
    ) -> Conversation | None:
        found = _theirs() if conversation_id == "theirs" else None
        owned = found and user_id in (None, found.metadata["user_id"])
        return found if owned else None

    monkeypatch.setattr(ai_service, "get_conversation", get_conversation)
    response = async_client_with_db.get(
        "/api/v1/ai/conversations/theirs", params={"user_id": "7"}, headers=MEMBER
    )
    assert response.status_code == 404
    assert "mine" not in response.text


TURNS: list[tuple[str, dict[str, Any]]] = [
    ("chat", {"url": "/api/v1/ai/chat", "json": {"message": "hi", "user_id": "7"}}),
    (
        "stream_chat",
        {"url": "/api/v1/ai/chat/stream", "json": {"message": "hi", "user_id": "7"}},
    ),
]
if HAS_VOICE:
    TURNS.append(
        (
            "voice_chat",
            {
                "url": "/api/v1/ai/voice-chat",
                "params": {"user_id": "7"},
                "files": {"audio": ("a.webm", b"x", "audio/webm")},
            },
        )
    )


@pytest.mark.parametrize(("turn", "request_kwargs"), TURNS)
def test_a_turn_is_the_callers_own(
    async_client_with_db: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    turn: str,
    request_kwargs: dict[str, Any],
) -> None:
    asked: list[str] = []

    async def nothing() -> AsyncIterator[Any]:
        return
        yield

    def record(**kwargs: Any) -> Any:
        """Who the turn is for; the turn itself is not run here."""
        asked.append(kwargs["user_id"])
        return nothing()

    monkeypatch.setattr(ai_service, turn, record)
    async_client_with_db.post(headers=MEMBER, **request_kwargs)
    assert asked == ["2"]


@pytest.mark.skipif(not HAS_CARDS, reason="cards are rows")
def test_another_users_card_is_not_read(
    async_client_with_db: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from app.components.backend.api.ai import cards as card_routes

    async def stored_card(card_id: str) -> Any:
        return SimpleNamespace(conversation_id="theirs")

    async def get_conversation(
        conversation_id: str, user_id: str | None = None
    ) -> Conversation | None:
        return _theirs() if user_id in (None, "7") else None

    monkeypatch.setattr(card_routes.cards, "stored_card", stored_card)
    monkeypatch.setattr(card_routes.cards, "kept", lambda row: ("kind", "card"))
    monkeypatch.setattr(ai_service, "get_conversation", get_conversation)
    response = async_client_with_db.get(
        "/api/v1/ai/cards/c1", params={"user_id": "7"}, headers=MEMBER
    )
    assert response.status_code == 404


@pytest.mark.parametrize(("turn", "request_kwargs"), TURNS)
def test_nobody_signed_in_takes_a_turn(
    async_client_with_db: TestClient, turn: str, request_kwargs: dict[str, Any]
) -> None:
    """No session, no turn: a model's answer is paid for, and a turn is
    some member's."""
    response = async_client_with_db.post(**request_kwargs)
    assert response.status_code == 401, response.text


@pytest.mark.skipif(
    find_spec("app.services.auth.domains.sessions.guest") is None,
    reason="guest sign-in is auth[guest]",
)
@pytest.mark.parametrize(("turn", "request_kwargs"), TURNS)
def test_a_guest_takes_no_turn_here(
    async_client_with_db: TestClient, turn: str, request_kwargs: dict[str, Any]
) -> None:
    """A guest is a visitor of the chat mounts that take guests
    (``guest_chat.for_visitors``), with their budget: never of this API,
    where it would name any agent and spend from no budget."""
    from app.core.visitor import GUEST_EMAIL

    response = async_client_with_db.post(headers=bearer(GUEST_EMAIL), **request_kwargs)
    assert response.status_code == 401, response.text


@pytest.mark.skipif(not HAS_VOICE, reason="speech is ai[voice]")
@pytest.mark.parametrize("path", ["/api/v1/ai/transcribe", "/api/v1/ai/synthesize"])
def test_nobody_signed_in_is_heard_or_spoken_to(
    async_client_with_db: TestClient, path: str
) -> None:
    """Hearing and speech are paid per use: a member's."""
    response = async_client_with_db.post(path, json={})
    assert response.status_code == 401, response.text
