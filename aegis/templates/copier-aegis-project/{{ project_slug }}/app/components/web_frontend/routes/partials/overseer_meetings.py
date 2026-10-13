"""Actions for the Overseer Meetings page: one meeting in the drawer, the
bot asked to leave it, and the meeting deleted. Mounted by
``routes/pages.py`` behind Overseer's gate; the admin reads and writes
every owner's meetings (``MeetingsService`` unscoped).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend import overseer_meetings
from app.components.web_frontend.rendering import dialog
from app.components.web_frontend.routes.meetings import meeting_context
from app.services.meetings.deps import as_http, get_every_owners_meetings
from app.services.meetings.service import MeetingsService

router = APIRouter(prefix=overseer_meetings.PARTIALS)
Every = Annotated[MeetingsService, Depends(get_every_owners_meetings)]


@router.get("/{meeting_id}/drawer", response_class=HTMLResponse)
async def drawer(request: Request, meeting_id: int, svc: Every) -> Response:
    return dialog(
        request,
        "pages/overseer/meetings/_drawer.html",
        partials=overseer_meetings.PARTIALS,
        **await meeting_context(svc, meeting_id),
    )


@router.post("/{meeting_id}/leave")
async def leave(meeting_id: int, svc: Every) -> Response:
    with as_http():
        await svc.ask_to_leave(meeting_id)
    return Response()


@router.get("/{meeting_id}/confirm-delete", response_class=HTMLResponse)
async def confirm_delete(request: Request, meeting_id: int) -> Response:
    return dialog(
        request,
        "pages/overseer/_confirm.html",
        title=f"Delete meeting {meeting_id}?",
        body="Its transcript, notes and speakers go with it, for good.",
        url=f"{overseer_meetings.PARTIALS}/{meeting_id}",
        label="Delete",
        method="delete",
        done="Meeting deleted",
    )


@router.delete("/{meeting_id}", status_code=204)
async def delete(meeting_id: int, svc: Every) -> Response:
    with as_http():
        await svc.delete(meeting_id)
    return Response(status_code=204)
