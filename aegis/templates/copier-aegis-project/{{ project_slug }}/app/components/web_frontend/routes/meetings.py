"""The Meetings page: send the bot to a call, follow it while it joins,
and read what came out of it. An app page (``/meetings``), not Overseer's:
each meeting is its owner's (``get_meetings_service``).

One meeting's page is a body that re-reads itself every few seconds while
something is still happening (the bot on its way in or in the call, the
notes being written), and stops once nothing is.
"""

from collections.abc import Callable
from itertools import groupby
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend.rendering import (
    fragment,
    navigate,
    render,
    status_cell,
    templates,
)
from app.core.formatting import format_clock, format_relative_time
from app.services.meetings.bot import send_bot
from app.services.meetings.deps import as_http, get_meetings_service
from app.services.meetings.models import Meeting, MeetingRecord, MeetingStatus
from app.services.meetings.service import (
    DEFAULT_BOT_NAME,
    MeetingsService,
    UnsupportedMeetingLinkError,
    call_length,
    heard_rows,
    status_label,
    voices,
)

router = APIRouter(prefix="/meetings")
# The navbar links the page wherever the stack has it (base.html).
templates.env.globals["meetings_page"] = "/meetings"
Service = Annotated[MeetingsService, Depends(get_meetings_service)]

LIST = "pages/meetings/index.html"
PAGE = "pages/meetings/meeting.html"
BODY = "pages/meetings/_body.html"
SEND = "pages/meetings/_send.html"
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


def send_form(
    send_url: str,
    url: str = "",
    bot_name: str = DEFAULT_BOT_NAME,
    error: str | None = None,
) -> dict[str, Any]:
    """The send form's context (_send.html), posting to ``send_url``."""
    return {"send_url": send_url, "url": url, "bot_name": bot_name, "error": error}


async def send_and_open(
    svc: MeetingsService,
    url: str,
    bot_name: str,
    send_url: str,
    opened: Callable[[int], str],
) -> Response:
    """Send the bot, then open its meeting at ``opened(id)``; a link it
    cannot join is the form again, saying why (422)."""
    try:
        meeting = await send_bot(svc, url, bot_name)
    except UnsupportedMeetingLinkError as exc:
        form = send_form(send_url, url, bot_name, str(exc))
        return HTMLResponse(fragment(SEND, **form), status_code=422)
    return navigate(Response(), opened(meeting.id))  # type: ignore[arg-type]


async def _list(request: Request, svc: MeetingsService) -> Response:
    meetings = await svc.list_meetings()
    notes = await svc.notes_for([m.id for m in meetings])  # type: ignore[misc]
    rows = []
    for m in meetings:
        kept = notes[m.id].notes() if m.id in notes else None  # type: ignore[index]
        mine = len(kept.mine(m.me)) if kept else None
        rows.append(row_of(m, f"/meetings/{m.id}") | {"mine": mine})
    return render(request, LIST, {"rows": rows} | send_form("/meetings"))


def body_context(record: MeetingRecord) -> dict[str, Any]:
    """What one meeting's body shows (and Overseer's drawer): the service's
    read of it, as it is, and how these pages draw it."""
    tone = TONES.get(record.meeting.status, "muted")
    owners = [i.owner for i in (record.notes.action_items if record.notes else [])]
    colors = voices([*record.people, *(owner for owner in owners if owner)])
    return dict(record) | {
        "status": status_cell(record.status, tone),
        # Each speaker's color (--aegis-chart-N), in the transcript, on the
        # action items they own, and in who talked (none: heard, not named).
        "voices": colors,
        # Who talked, as the house's ranked rows: audio no caption named
        # stands apart, unmarked.
        "talk": [
            {
                "label": name,
                "value": span,
                "ratio": ratio,
                "dot": colors.get(name),
                "tone": None if name in colors else "muted",
            }
            for name, span, ratio in heard_rows(record.meeting.heard)
        ],
        # One speaker's lines in a row, under their name once.
        "turns": [
            (speaker, list(rows))
            for speaker, rows in groupby(record.transcript, key=lambda r: r.speaker)
        ],
        "clock": {row.id: format_clock(row.at) for row in record.transcript},
        "people": [{"id": name, "name": name} for name in record.people],
    }


async def meeting_context(svc: MeetingsService, meeting_id: int) -> dict[str, Any]:
    with as_http():
        return body_context(await svc.read(meeting_id))


@router.get("", response_class=HTMLResponse)
async def meetings(request: Request, svc: Service) -> Response:
    return await _list(request, svc)


@router.post("")
async def join(
    request: Request,
    svc: Service,
    url: Annotated[str, Form()],
    bot_name: Annotated[str, Form()] = "",
) -> Response:
    """Send the bot in, then open its meeting."""
    return await send_and_open(
        svc, url, bot_name, "/meetings", lambda meeting_id: f"/meetings/{meeting_id}"
    )


@router.get("/{meeting_id}", response_class=HTMLResponse)
async def meeting_page(request: Request, svc: Service, meeting_id: int) -> Response:
    context = await meeting_context(svc, meeting_id) | {"prefix": "/meetings"}
    return render(request, PAGE, context)


def meeting_routes(
    router: APIRouter, service: Callable[..., Any], body: str, prefix: str
) -> None:
    """The routes one meeting's live body answers: it re-reads itself, asks
    the bot to leave, says which speaker the owner is, writes the notes
    again. The Meetings page and Overseer's drawer register the same ones,
    each with its own service scope, body template and URL ``prefix`` (the
    router's own)."""
    scoped = Annotated[MeetingsService, Depends(service)]

    def drawn(record: MeetingRecord) -> HTMLResponse:
        return HTMLResponse(fragment(body, **body_context(record), prefix=prefix))

    async def read(svc: MeetingsService, meeting_id: int) -> HTMLResponse:
        with as_http():
            return drawn(await svc.read(meeting_id))

    @router.get("/{meeting_id}/body", response_class=HTMLResponse)
    async def live(svc: scoped, meeting_id: int) -> HTMLResponse:  # type: ignore[valid-type]
        return await read(svc, meeting_id)

    @router.post("/{meeting_id}/leave", response_class=HTMLResponse)
    async def leave(svc: scoped, meeting_id: int) -> HTMLResponse:  # type: ignore[valid-type]
        with as_http():
            await svc.ask_to_leave(meeting_id)
        return await read(svc, meeting_id)

    @router.post("/{meeting_id}/me", response_class=HTMLResponse)
    async def set_me(
        svc: scoped,  # type: ignore[valid-type]
        meeting_id: int,
        name: Annotated[str, Form()] = "",
    ) -> HTMLResponse:
        """Which speaker the meeting's owner is; their action items follow."""
        with as_http():
            await svc.set_me(meeting_id, name or None)
        return await read(svc, meeting_id)

    @router.post("/{meeting_id}/notes", response_class=HTMLResponse)
    async def write_notes(svc: scoped, meeting_id: int) -> HTMLResponse:  # type: ignore[valid-type]
        """Write the notes again, over the old ones."""
        with as_http():
            return drawn(await svc.write_notes_again(meeting_id))


meeting_routes(router, get_meetings_service, BODY, "/meetings")
