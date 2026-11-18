"""Drawn cards: a card the assistant drew in a reply (``draw_card``), as
its kind and the payload that kind keeps. The Flet chat draws it from
this; the htmx thread draws the same row server-side (``chat_cards``).

Its own sub-router (the memory endpoints' pattern): cards are rows, so it
ships only with a database backend.
"""

from typing import Any

from fastapi import APIRouter, HTTPException

from app.components.backend.api.ai.service import ai_service
from app.services.ai.service import cards

router = APIRouter()


@router.get("/cards/{card_id}")
async def get_card(card_id: str, user_id: str = "api-user") -> dict[str, Any]:
    """The card ``card_id``. Gone, of a kind that is gone, or in another
    user's conversation: 404."""
    row = await cards.stored_card(card_id)
    conversation = (
        await ai_service.get_conversation(row.conversation_id) if row else None
    )
    found = cards.kept(row) if row else None
    if (
        found is None
        or conversation is None
        or conversation.metadata.get("user_id") != user_id
    ):
        raise HTTPException(status_code=404, detail="Card not found")
    kind, kept = found
    return {"id": card_id, "kind": kind.name, "card": kept.model_dump()}
