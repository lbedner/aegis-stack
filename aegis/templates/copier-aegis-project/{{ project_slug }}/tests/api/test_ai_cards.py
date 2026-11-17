"""A drawn card over the API (``api/ai/cards.py``): its kind and the
payload it keeps, what the Flet chat draws it from. Gone, of a kind that
is gone, or in another user's conversation, it is a 404."""

from typing import Any

from fastapi.testclient import TestClient
import pytest

from app.components.backend.api.ai.service import ai_service
from app.integrations.main import create_integrated_app
from app.services.ai.models import AIProvider
from app.services.ai.models.chat_card import ChatCard

TREND: dict[str, Any] = {
    "title": "Groceries by month",
    "measure": "Spent",
    "rows": [{"date": "2026-08-01", "value": 61_250}],
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_integrated_app())


async def _drawn(kind: str = "trend", payload: dict[str, Any] = TREND) -> str:
    """A card ``kind`` drew in a conversation of ``owner``'s."""
    from app.core.db import get_async_session

    conversation = await ai_service.conversation_manager.create_conversation(
        provider=AIProvider.OLLAMA, model="m", user_id="owner"
    )
    await ai_service.conversation_manager.save_conversation(conversation)
    async with get_async_session() as session:
        card = ChatCard(conversation_id=conversation.id, kind=kind, payload=payload)
        session.add(card)
    return card.id


async def test_a_card_is_its_kind_and_payload(client: TestClient) -> None:
    card_id = await _drawn()

    body = client.get(f"/api/v1/ai/cards/{card_id}", params={"user_id": "owner"}).json()

    assert (body["id"], body["kind"]) == (card_id, "trend")
    assert body["card"]["title"] == "Groceries by month"
    # Read through the kind's shape: its defaults fill in.
    assert body["card"]["unit"] == "money"


@pytest.mark.parametrize(
    ("kind", "user_id"),
    [("trend", "someone-else"), ("retired", "owner")],
)
async def test_another_users_card_or_a_gone_kind_is_not_found(
    client: TestClient, kind: str, user_id: str
) -> None:
    card_id = await _drawn(kind)

    answer = client.get(f"/api/v1/ai/cards/{card_id}", params={"user_id": user_id})

    assert answer.status_code == 404


def test_a_card_that_is_gone_is_not_found(client: TestClient) -> None:
    answer = client.get("/api/v1/ai/cards/nope", params={"user_id": "owner"})

    assert answer.status_code == 404
