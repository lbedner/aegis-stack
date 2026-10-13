"""The Meetings page: send the bot to a call, follow it while it joins,
and read what came out of it. An app page (``/meetings``), not Overseer's:
each meeting is its owner's (``get_meetings_service``).

One meeting's page is a body that re-reads itself every few seconds while
something is still happening (the bot on its way in or in the call, the
notes being written), and stops once nothing is.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend.rendering import (
    fragment,
    navigate,
    render,
    status_cell,
    templates,
)
from app.core.concurrency import background
from app.core.formatting import format_clock, format_relative_time
from app.services.meetings.bot import start_meeting
from app.services.meetings.deps import as_http, get_meetings_service
from app.services.meetings.models import Meeting, MeetingStatus
from app.services.meetings.service import (
    DEFAULT_BOT_NAME,
    NOT_DONE,
    WRITING,
    MeetingsService,
    UnsupportedMeetingLinkError,
    call_length,
    notes_writer,
    status_label,
)

router = APIRouter(prefix="/meetings")
# The navbar links the page wherever the stack has it (base.html).
templates.env.globals["meetings_page"] = "/meetings"
Service = Annotated[MeetingsService, Depends(get_meetings_service)]

LIST = "pages/meetings/index.html"
PAGE = "pages/meetings/meeting.html"
BODY = "pages/meetings/_body.html"
TONES = {
    MeetingStatus.JOINING: "accent",
    MeetingStatus.WAITING: "warn",
    MeetingStatus.IN_CALL: "ok",
    MeetingStatus.LEAVING: "accent",
    MeetingStatus.FAILED: "error",
}


def status_of(meeting: Meeting) -> dict[str, str]:
    return status_cell(status_label(meeting.status), TONES.get(meeting.status, "muted"))


def row_of(meeting: Meeting, url: str) -> dict[str, Any]:
    """One meeting's table row, opening ``url`` (this page's list and
    Overseer's)."""
    return {
        "id": meeting.id,
        "meeting": {"label": meeting.url, "url": url},
        "requested": format_relative_time(meeting.created_at),
        "status": status_of(meeting),
        "length": call_length(meeting.joined_at, meeting.left_at),
    }


async def _list(request: Request, svc: MeetingsService, **form: Any) -> Response:
    meetings = await svc.list_meetings()
    notes = await svc.notes_for([m.id for m in meetings])  # type: ignore[misc]
    rows = []
    for m in meetings:
        kept = notes[m.id].notes() if m.id in notes else None  # type: ignore[index]
        mine = len(kept.mine(m.me)) if kept else None
        rows.append(row_of(m, f"/meetings/{m.id}") | {"mine": mine})
    context = {"rows": rows, "url": "", "bot_name": DEFAULT_BOT_NAME, "error": None}
    context |= form
    return render(request, LIST, context, status_code=422 if "error" in form else 200)


async def meeting_context(svc: MeetingsService, meeting_id: int) -> dict[str, Any]:
    """Everything one meeting's body shows (and Overseer's drawer): the
    service's read of it (``MeetingsService.read``, which Overseer's API
    returns as it is), and what only these pages need."""
    with as_http():
        record = await svc.read(meeting_id)
    meeting, notes = record.meeting, record.notes
    writing = meeting_id in WRITING
    under_way = meeting.status in NOT_DONE
    lines = record.transcript
    can_write = notes_writer() is not None
    # Only a speaker has a participant row, so the transcript names them all.
    people = sorted({row.speaker for row in record.transcript})
    return {
        "meeting": meeting,
        "status": status_cell(record.status, TONES.get(meeting.status, "muted")),
        "length": record.length,
        "heard": record.heard,
        "can_leave": record.can_leave,
        "can_delete": record.can_delete,
        "lines": lines,
        "clock": {row.id: format_clock(row.at) for row in lines},
        "people": [{"id": name, "name": name} for name in people],
        "notes": notes,
        "mine": notes.mine(meeting.me) if notes else [],
        "notes_error": record.notes_error,
        "model_name": record.model_name,
        "writing": writing,
        "can_write": can_write,
        # Written again now: the call is over, something was said, and no
        # writer is already at it.
        "can_rewrite": can_write and bool(lines) and not under_way and not writing,
        "under_way": under_way,
    }


@router.get("", response_class=HTMLResponse)
async def meetings(request: Request, svc: Service) -> Response:
    return await _list(request, svc)


@router.post("")
async def join(
    request: Request,
    svc: Service,
    url: Annotated[str, Form()],
    bot_name: Annotated[str, Form()] = DEFAULT_BOT_NAME,
) -> Response:
    """Send the bot in, then open its meeting."""
    try:
        meeting = await svc.request(url, bot_name.strip() or DEFAULT_BOT_NAME)
    except UnsupportedMeetingLinkError as exc:
        return await _list(request, svc, error=str(exc), url=url, bot_name=bot_name)
    start_meeting(meeting.id)  # type: ignore[arg-type]
    return navigate(Response(), f"/meetings/{meeting.id}")


@router.get("/{meeting_id}", response_class=HTMLResponse)
async def meeting_page(request: Request, svc: Service, meeting_id: int) -> Response:
    return render(request, PAGE, await meeting_context(svc, meeting_id))


@router.get("/{meeting_id}/body", response_class=HTMLResponse)
async def meeting_body(svc: Service, meeting_id: int) -> HTMLResponse:
    return HTMLResponse(fragment(BODY, **await meeting_context(svc, meeting_id)))


@router.post("/{meeting_id}/leave", response_class=HTMLResponse)
async def leave(svc: Service, meeting_id: int) -> HTMLResponse:
    with as_http():
        await svc.ask_to_leave(meeting_id)
    return await meeting_body(svc, meeting_id)


@router.post("/{meeting_id}/me", response_class=HTMLResponse)
async def set_me(
    svc: Service, meeting_id: int, name: Annotated[str, Form()] = ""
) -> HTMLResponse:
    """Which speaker the owner is; my action items follow."""
    with as_http():
        await svc.set_me(meeting_id, name or None)
    return await meeting_body(svc, meeting_id)


@router.post("/{meeting_id}/notes", response_class=HTMLResponse)
async def write_notes(svc: Service, meeting_id: int) -> HTMLResponse:
    """Write the notes again, over the old ones."""
    context = await meeting_context(svc, meeting_id)
    write = notes_writer()
    if write is None or not context["can_rewrite"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "No notes to write now")
    WRITING.add(meeting_id)
    background(write(meeting_id))
    context |= {"writing": True, "can_rewrite": False}
    return HTMLResponse(fragment(BODY, **context))
