"""The card a reply drew, on any mount of the chat surface.

A drawn card rides its answer's trace as a ``chat_card`` marker; the
settled message places a loader for it (``card_loader``), and this draws
the kind's template from the card's frozen payload. A card that is gone,
whose kind is gone, or that belongs to another user's conversation says so
quietly: 200, never 404, because a transcript is a record.

``add_card_routes(router, mount)`` adds it to a mount's router; the chat
router does, where there is a database to keep cards in.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError

from app.components.web_frontend import chat_surface as chat
from app.components.web_frontend.chat_surface import ChatSurface
from app.components.web_frontend.rendering import dialog, templates
from app.services.ai.domains.chat import cards

MISSING = "partials/chat/card_missing.html"


def add_card_routes(router: APIRouter, mount: ChatSurface) -> None:
    """A drawn card under ``mount.path``/cards, small or opened larger."""

    @router.get("/cards/{card_id}", response_class=HTMLResponse)
    async def card(request: Request, card_id: str, size: str = "") -> Response:
        row = await cards.stored_card(card_id)
        kind = cards.lookup(row.kind) if row else None
        if (
            row is None
            or kind is None
            or await chat.find_conversation(mount, row.conversation_id) is None
        ):
            return templates.TemplateResponse(request=request, name=MISSING)
        try:
            # Read through the kind's schema: its defaults fill in, and a
            # payload an old version stored in another shape is missing,
            # not a template error.
            payload = kind.schema.model_validate(row.payload).model_dump()
        except ValidationError:
            return templates.TemplateResponse(request=request, name=MISSING)
        context = {
            "card": payload,
            "card_id": row.id,
            "card_url": f"{mount.path}/cards/{row.id}",
            "large": size == "large",
        }
        if context["large"]:
            return dialog(request, kind.template, **context)
        return templates.TemplateResponse(
            request=request, name=kind.template, context=context
        )
