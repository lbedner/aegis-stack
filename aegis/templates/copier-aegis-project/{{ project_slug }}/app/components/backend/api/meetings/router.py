"""Meetings over HTTP: ask the bot into a call, read how it is going and
what it came to (its threads), and ask it to leave. Scoped to the caller (``get_meetings_service``)."""

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.services.meetings.deps import as_http, get_meetings_service
from app.services.meetings.domains.bot.run import send_bot
from app.services.meetings.domains.threads.service import meeting_threads
from app.services.meetings.models import Meeting, ThreadSection
from app.services.meetings.service import MeetingsService

router = APIRouter(prefix="/meetings", tags=["meetings"])


class MeetingRequest(BaseModel):
    url: str
    # The agent to send, by name; the default when not given.
    agent: str | None = None
    # The name it joins as; the agent's own when blank.
    bot_name: str = ""


@router.post("", response_model=Meeting, status_code=status.HTTP_202_ACCEPTED)
async def join_meeting(
    body: MeetingRequest, svc: MeetingsService = Depends(get_meetings_service)
) -> Meeting:
    """Record the meeting and start the bot on it; answers before it joins."""
    with as_http():
        return await send_bot(svc, body.url, body.bot_name, body.agent)


@router.get("/{meeting_id}", response_model=Meeting)
async def get_meeting(
    meeting_id: int, svc: MeetingsService = Depends(get_meetings_service)
) -> Meeting:
    with as_http():
        return await svc.get(meeting_id)


@router.get("/{meeting_id}/threads", response_model=list[ThreadSection])
async def get_threads(
    meeting_id: int, svc: MeetingsService = Depends(get_meetings_service)
) -> list[ThreadSection]:
    """Its commitments, contradictions and positions, with their lines."""
    with as_http():
        return await meeting_threads(svc, meeting_id)


@router.post(
    "/{meeting_id}/leave",
    response_model=Meeting,
    status_code=status.HTTP_202_ACCEPTED,
)
async def leave_meeting(
    meeting_id: int, svc: MeetingsService = Depends(get_meetings_service)
) -> Meeting:
    """Ask the bot to leave; it goes on its next look."""
    with as_http():
        return await svc.ask_to_leave(meeting_id)
