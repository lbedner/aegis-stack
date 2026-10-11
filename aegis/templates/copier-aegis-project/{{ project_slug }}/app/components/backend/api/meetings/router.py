"""Meetings over HTTP: ask the bot into a call, read how it is going, and
ask it to leave. Scoped to the caller (``get_meetings_service``)."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.services.meetings.bot import start_meeting
from app.services.meetings.deps import get_meetings_service
from app.services.meetings.models import Meeting
from app.services.meetings.service import (
    DEFAULT_BOT_NAME,
    MeetingNotFoundError,
    MeetingsService,
    UnsupportedMeetingLinkError,
)

router = APIRouter(prefix="/meetings", tags=["meetings"])


class MeetingRequest(BaseModel):
    url: str
    bot_name: str = DEFAULT_BOT_NAME


@router.post("", response_model=Meeting, status_code=status.HTTP_202_ACCEPTED)
async def join_meeting(
    body: MeetingRequest, svc: MeetingsService = Depends(get_meetings_service)
) -> Meeting:
    """Record the meeting and start the bot on it; answers before it joins."""
    try:
        meeting = await svc.request(body.url, body.bot_name)
    except UnsupportedMeetingLinkError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    start_meeting(meeting.id)  # type: ignore[arg-type]
    return meeting


@router.get("/{meeting_id}", response_model=Meeting)
async def get_meeting(
    meeting_id: int, svc: MeetingsService = Depends(get_meetings_service)
) -> Meeting:
    try:
        return await svc.get(meeting_id)
    except MeetingNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e


@router.post(
    "/{meeting_id}/leave",
    response_model=Meeting,
    status_code=status.HTTP_202_ACCEPTED,
)
async def leave_meeting(
    meeting_id: int, svc: MeetingsService = Depends(get_meetings_service)
) -> Meeting:
    """Ask the bot to leave; it goes on its next look."""
    try:
        return await svc.ask_to_leave(meeting_id)
    except MeetingNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
