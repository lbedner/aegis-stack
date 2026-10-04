"""The Overseer's mount of the chat surface: its pages (``chat_router``)
behind the Overseer's sign-in, plus the reply's agent drawer (the
Overseer's agent editor), and - where voice and a database are both
installed - the live call's socket (``live_router``), which the web
frontend mounts outside the pages' gate (a socket has no HTTP request for
it to read)."""

from typing import Any

from fastapi import Cookie, Depends, HTTPException, Request, WebSocketException, status
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend import chat_surface
from app.components.web_frontend.chat_surface import HAS_VOICE, PERSISTED
from app.components.web_frontend.overseer_ai_chat import OVERSEER, reply_agent_context
from app.components.web_frontend.rendering import dialog
from app.core.security import SESSION_COOKIE_NAME
from app.models.user import User
from app.services.auth.deps import get_optional_user, get_user_service, is_admin
from app.services.auth.users import UserService

from .chat_surface import chat_router
from .overseer_auth import signed_in


async def _signed_in(user: User | None = Depends(get_optional_user)) -> None:
    signed_in(user)


async def _signed_in_socket(
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    user_service: UserService = Depends(get_user_service),
) -> None:
    """The live call's sign-in, the Overseer's own rule (an admin): a socket
    carries the session cookie, never a bearer header."""
    user = await get_optional_user(session, user_service)
    if user is None or not is_admin(user):
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)


router = chat_router(OVERSEER, _signed_in)


@router.get(
    "/messages/{conversation_id}/{message_id}/agent", response_class=HTMLResponse
)
async def reply_agent(
    request: Request,
    conversation_id: str,
    message_id: str,
    focus: str | None = None,
) -> Response:
    """The agent behind a reply, in the side drawer: what the reply used,
    then the live settings. ``focus`` names the field to land on."""
    conversation = await chat_surface.find_conversation(OVERSEER, conversation_id)
    found = conversation and chat_surface.find_message(conversation, message_id)
    if not found:
        raise HTTPException(status_code=404)
    from app.core.db import get_async_session

    async with get_async_session() as db:
        context = await reply_agent_context(db, found, focus)
    if context is None:
        raise HTTPException(status_code=404, detail="No such agent.")
    return dialog(request, "pages/overseer/ai/_agent_drawer.html", **context)


sockets: Any = None
if HAS_VOICE and PERSISTED:
    from .chat_live import live_router

    sockets = live_router(OVERSEER, _signed_in_socket)
