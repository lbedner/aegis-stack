"""Meetings for Overseer, across every owner: the list, one meeting read in
full (its notes, transcript and how long each speaker was heard), the bot
asked to leave, and a meeting deleted. Reading is the admin's
(``get_admin_reader``), a change an operator's (``get_admin_actor``); an
owner's own meetings are ``router``'s."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.services.meetings.deps import as_http, get_every_owners_meetings
from app.services.meetings.models import Meeting, MeetingRecord
from app.services.meetings.service import MeetingsService
from app.services.shared.deps import get_admin_actor, get_admin_reader

LIMIT = 200

router = APIRouter(prefix="/meetings/admin", tags=["meetings"])
Every = Annotated[MeetingsService, Depends(get_every_owners_meetings)]
READ = [Depends(get_admin_reader)]
CHANGE = [Depends(get_admin_actor)]


@router.get("", response_model=list[Meeting], dependencies=READ)
async def every_meeting(svc: Every) -> list[Meeting]:
    """Every owner's meetings, newest first."""
    return await svc.list_meetings(LIMIT)


@router.get("/{meeting_id}", response_model=MeetingRecord, dependencies=READ)
async def one_meeting(meeting_id: int, svc: Every) -> MeetingRecord:
    """The meeting, its notes (or why there are none) and its transcript."""
    with as_http():
        return await svc.read(meeting_id)


@router.post(
    "/{meeting_id}/leave",
    response_model=Meeting,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=CHANGE,
)
async def leave(meeting_id: int, svc: Every) -> Meeting:
    """Ask the bot to leave; it goes on its next look."""
    with as_http():
        return await svc.ask_to_leave(meeting_id)


@router.delete(
    "/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=CHANGE
)
async def delete(meeting_id: int, svc: Every) -> Response:
    """The meeting and everything kept of it; refused while the bot is in."""
    with as_http():
        await svc.delete(meeting_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
