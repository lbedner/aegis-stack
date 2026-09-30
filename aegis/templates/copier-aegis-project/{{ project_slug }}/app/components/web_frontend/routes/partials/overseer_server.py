"""Fragments for the Overseer Server page: one connection's timeline in
the drawer. Mounted by ``routes/pages.py``."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend import overseer_connections
from app.components.web_frontend.rendering import dialog
from app.models.user import User
from app.services.auth.deps import get_optional_user

from .overseer_auth import signed_in

router = APIRouter(prefix=overseer_connections.PARTIALS)


@router.get("/{record_id}/drawer", response_class=HTMLResponse)
async def connection_drawer(
    request: Request, record_id: str, user: User | None = Depends(get_optional_user)
) -> Response:
    signed_in(user)
    context = await overseer_connections.drawer_context(record_id)
    if context is None:
        raise HTTPException(
            status_code=404, detail="That connection is no longer remembered."
        )
    return dialog(request, "pages/overseer/server/_connection_drawer.html", **context)
