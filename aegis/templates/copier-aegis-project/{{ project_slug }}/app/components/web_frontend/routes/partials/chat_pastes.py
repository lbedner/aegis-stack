"""What was pasted into a chat, on any mount of the chat surface.

The composer hands a wall of text over the moment it is pasted (only the
browser knows a paste was a paste: finished text cannot say which part was
typed) and puts the marker it gets back in the box, past the mount's gate
like a turn. A question's chip opens what it stands for, whole, in the
modal. Both read the mount's user's own index (``pastes``), a document's
pages in the request's owner's scope.

``add_paste_routes(router, mount)`` adds them to a mount's router; the chat
router does, where there is a database to keep the index in.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.web_frontend import chat_surface as chat
from app.components.web_frontend.chat_attachments import paste_chips
from app.components.web_frontend.chat_surface import ChatSurface
from app.components.web_frontend.rendering import dialog
from app.core.chat_transcript import MAX_ATTACHMENT_BYTES
from app.core.db import get_async_db
from app.services.ai.service import read_paste, store_paste
from app.services.shared.deps import get_optional_owner_user_id


def add_paste_routes(router: APIRouter, mount: ChatSurface) -> None:
    """A paste kept as it lands, and one opened, under ``mount.path``/pastes."""

    # The mount this request is served (``ChatSurface.bind``).
    Mount = Annotated[ChatSurface, Depends(chat.resolver(mount))]  # noqa: N806

    @router.post("/pastes")
    async def keep(
        bound: Mount,
        refusal: Annotated[str | None, Depends(chat.gatekeeper(mount))],
        db: Annotated[AsyncSession, Depends(get_async_db)],
        text: Annotated[str, Form()] = "",
    ) -> Response:
        """Keep a pasted wall of text; the marker that stands in for it. A
        refusal (the gate's, or past the size a file may be) leaves the
        composer to put the text in as text."""
        if refusal:
            return JSONResponse({"error": refusal}, status_code=403)
        if not text.strip():
            return Response(status_code=422)
        if len(text.encode()) > MAX_ATTACHMENT_BYTES:
            return Response(status_code=413)
        paste = await store_paste(db, bound.user, text)
        return JSONResponse({"marker": paste.marker})

    @router.get("/pastes/{paste_id}", response_class=HTMLResponse)
    async def opened(
        request: Request,
        bound: Mount,
        paste_id: str,
        owner_user_id: Annotated[int | None, Depends(get_optional_owner_user_id)],
        db: Annotated[AsyncSession, Depends(get_async_db)],
    ) -> Response:
        """A paste, shown as it was pasted: a page reflowed as prose would
        change the thing the reader opened it to check."""
        found = await read_paste(db, bound.user, paste_id, owner_user_id=owner_user_id)
        if found is None:
            raise HTTPException(status_code=404)
        paste, text = found
        (chip,) = paste_chips(bound, [paste.model_dump()])
        return dialog(request, "partials/chat/paste.html", paste=chip, text=text)
