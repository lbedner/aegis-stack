"""Actions for the Overseer Meetings page: the bot sent from there, one
meeting in the drawer (live, with which speaker is me and the notes
written again, as the Meetings page has them), the bot asked to leave it,
and the meeting deleted. Mounted by ``routes/pages.py`` behind Overseer's
gate; the admin reads and writes every owner's meetings (``Every``), and
a meeting the admin sends is the admin's own (``Mine``).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend import overseer_meetings
from app.components.web_frontend.rendering import dialog, with_query
from app.components.web_frontend.routes.meetings import (
    meeting_context,
    meeting_routes,
    send_and_open,
)
from app.services.meetings.deps import (
    as_http,
    get_every_owners_meetings,
    get_meetings_service,
)
from app.services.meetings.service import MeetingsService

PREFIX = overseer_meetings.PARTIALS
router = APIRouter(prefix=PREFIX)
Every = Annotated[MeetingsService, Depends(get_every_owners_meetings)]
Mine = Annotated[MeetingsService, Depends(get_meetings_service)]

DRAWER = "pages/overseer/meetings/_drawer.html"
BODY = "pages/overseer/meetings/_drawer_body.html"


@router.post("")
async def send(
    svc: Mine, url: Annotated[str, Form()], bot_name: Annotated[str, Form()] = ""
) -> Response:
    """Send the bot as the admin, then open its meeting in the drawer."""
    return await send_and_open(
        svc,
        url,
        bot_name,
        PREFIX,
        lambda meeting_id: with_query(
            overseer_meetings.PAGE, **{overseer_meetings.DRAWER_PARAM: str(meeting_id)}
        ),
    )


@router.get("/{meeting_id}/drawer", response_class=HTMLResponse)
async def drawer(request: Request, meeting_id: int, svc: Every) -> Response:
    context = await meeting_context(svc, meeting_id) | {"prefix": PREFIX}
    return dialog(request, DRAWER, **context)


# The drawer's live part: re-read while the bot is in or the notes are being
# written; the bot asked to leave, which speaker the owner is, the notes
# written again, the same routes as the Meetings page's.
meeting_routes(router, get_every_owners_meetings, BODY, PREFIX)


@router.get("/{meeting_id}/confirm-delete", response_class=HTMLResponse)
async def confirm_delete(request: Request, meeting_id: int) -> Response:
    return dialog(
        request,
        "pages/overseer/_confirm.html",
        title=f"Delete meeting {meeting_id}?",
        body="Its transcript, notes and speakers go with it, for good.",
        url=f"{PREFIX}/{meeting_id}",
        label="Delete",
        method="delete",
        done="Meeting deleted",
    )


@router.delete("/{meeting_id}", status_code=204)
async def delete(meeting_id: int, svc: Every) -> Response:
    with as_http():
        await svc.delete(meeting_id)
    return Response(status_code=204)
