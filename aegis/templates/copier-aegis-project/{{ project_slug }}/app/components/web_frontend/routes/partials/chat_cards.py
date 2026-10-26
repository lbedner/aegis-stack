"""The card a reply drew, on any mount of the chat surface.

A drawn card rides its answer's trace as a ``chat_card`` marker; the
settled message places a loader for it (``card_loader``), and this draws
the kind's template from the card's frozen payload. A card that is gone,
whose kind is gone, or that belongs to another user's conversation says so
quietly: 200, never 404, because a transcript is a record.

``add_card_routes(router, mount)`` adds it to a mount's router; the chat
router does, where there is a database to keep cards in.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError

from app.components.web_frontend import chat_surface as chat
from app.components.web_frontend import overseer_replay
from app.components.web_frontend.chat_surface import ChatSurface
from app.components.web_frontend.rendering import dialog, fragment, templates
from app.services.ai.service import PathCard, cards

MISSING = "partials/chat/card_missing.html"


def add_card_routes(router: APIRouter, mount: ChatSurface) -> None:
    """A drawn card under ``mount.path``/cards, small or opened larger."""

    # The mount this request is served (``ChatSurface.bind``).
    Mount = Annotated[ChatSurface, Depends(chat.resolver(mount))]  # noqa: N806

    @router.get("/cards/{card_id}", response_class=HTMLResponse)
    async def card(
        request: Request, bound: Mount, card_id: str, size: str = ""
    ) -> Response:
        row = await cards.stored_card(card_id)
        if (
            row is None
            or await chat.find_conversation(bound, row.conversation_id) is None
        ):
            return templates.TemplateResponse(request=request, name=MISSING)
        large = size == "large"
        found = await drawn(row, f"{mount.path}/cards/{row.id}", large)
        if found is None:
            return templates.TemplateResponse(request=request, name=MISSING)
        template, context = found
        if large:
            return dialog(request, template, **context)
        return templates.TemplateResponse(
            request=request, name=template, context=context
        )


async def drawn(
    row: Any, url: str, large: bool = False
) -> tuple[str, dict[str, Any]] | None:
    """A kept card (``cards.stored_card``) as its kind draws it: the template
    and what it is drawn with, at ``url`` (where it opens larger, unless
    drawn ``large`` already); None for a card whose kind is gone, or whose
    payload an old version kept in another shape."""
    kind = cards.lookup(row.kind)
    if kind is None:
        return None
    try:
        # Read through the shape the kind keeps: its defaults fill in.
        kept = kind.stored.model_validate(row.payload)
    except ValidationError:
        return None
    context = {
        "card": kept.model_dump(),
        "card_id": row.id,
        "card_url": url,
        "large": large,
    }
    # A path card's map and steps, played as the Replay page plays them:
    # drawn from its hops, not kept with them.
    if isinstance(kept, PathCard) and kept.node:
        context |= await overseer_replay.wiring(kept.node)
    elif isinstance(kept, PathCard) and kept.path:
        context |= await overseer_replay.card(kept.path, large)
    return kind.template, context


async def drawn_full(card_id: str) -> dict[str, Any]:
    """The card ``card_id``, drawn full size (``card``), and where the part
    it draws lives in Overseer (``part``); nothing for a card that is gone."""
    from app.components.web_frontend.overseer_database_browser import owner_link

    row = await cards.stored_card(card_id)
    found = await drawn(row, "", large=True) if row else None
    if found is None:
        return {}
    template, context = found
    node = context["card"].get("node")
    return {"card": fragment(template, **context), "part": owner_link(node)}
