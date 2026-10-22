"""The Meetings page: send the bot to a call, follow it while it joins,
and read what came out of it. An app page (``/meetings``), not Overseer's:
each meeting is its owner's (``get_meetings_service``).

One meeting's page is a body that re-reads itself every few seconds while
something is still happening (the bot on its way in or in the call, the
notes being written), and stops once nothing is.
"""

from collections.abc import Callable
from itertools import groupby
from operator import attrgetter
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend.meeting_agents import agent_options
from app.components.web_frontend.meeting_calendar import calendar_context
from app.components.web_frontend.meeting_status import TONES, state_cell
from app.components.web_frontend.rendering import (
    fragment,
    navigate,
    render,
    status_cell,
    templates,
    viewer_zone,
)
from app.core.formatting import format_clock, format_relative_time
from app.services.meetings.deps import as_http, get_meetings_service
from app.services.meetings.domains.accounts.service import AgentNotFoundError, agents
from app.services.meetings.domains.calendar.owners import email_of
from app.services.meetings.models import Meeting, MeetingRecord
from app.services.meetings.service import (
    MeetingsService,
    UnsupportedMeetingLinkError,
    by_kind,
    call_length,
    heard_rows,
    send_bot,
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


def status_of(meeting: Meeting) -> dict[str, str]:
    return state_cell(meeting.status)


def row_of(meeting: Meeting, url: str) -> dict[str, Any]:
    """One meeting's table row, opening ``url`` (this page's list and
    Overseer's)."""
    return {
        "id": meeting.id,
        # Its calendar's name for it, the link under it; else the link.
        "meeting": {
            "label": meeting.title or meeting.url,
            "url": url,
            "sub": meeting.url if meeting.title else None,
        },
        "requested": format_relative_time(meeting.created_at),
        "status": status_of(meeting),
        "length": call_length(meeting.joined_at, meeting.left_at),
    }


# How many links the bot was sent to before the send form offers.
RECENT_LINKS = 10


def send_form(
    send_url: str,
    url: str = "",
    bot_name: str = "",
    error: str | None = None,
    agents: list[dict[str, str]] | None = None,
    agent: str | None = None,
    meetings: list[Meeting] | None = None,
) -> dict[str, Any]:
    """The send form's context (_send.html), posting to ``send_url``, with
    the agents to pick from (``agent_options``) and the links of
    ``meetings`` (newest first) offered as the link, each once."""
    links: dict[str, str | None] = {}
    for m in meetings or []:  # newest first: each link where it was last used
        links[m.url] = links.get(m.url) or m.title
    return {
        "send_url": send_url,
        "url": url,
        "bot_name": bot_name,
        "error": error,
        "agents": agents or [],
        "agent": agent,
        "links": [
            {"url": link, "title": title}
            for link, title in list(links.items())[:RECENT_LINKS]
        ],
    }


async def send_and_open(
    svc: MeetingsService,
    url: str,
    bot_name: str,
    send_url: str,
    opened: Callable[[int], str],
    agent: str | None = None,
) -> Response:
    """Send the bot as ``agent``, then open its meeting at ``opened(id)``;
    a link it cannot join (or an agent there is not) is the form again,
    saying why (422)."""
    every = await agents(svc.db)
    try:
        meeting = await send_bot(svc, url, bot_name, agent, every)
    except (UnsupportedMeetingLinkError, AgentNotFoundError) as exc:
        options = agent_options(every)
        sent = await svc.list_meetings()
        form = send_form(send_url, url, bot_name, str(exc), options, agent, sent)
        return HTMLResponse(fragment(SEND, **form), status_code=422)
    return navigate(Response(), opened(meeting.id))  # type: ignore[arg-type]


async def _list(request: Request, svc: MeetingsService) -> Response:
    meetings = await svc.list_meetings()
    mine = await svc.mine_counts([m.id for m in meetings])  # type: ignore[misc]
    rows = [
        row_of(m, f"/meetings/{m.id}") | {"mine": mine.get(m.id)}  # type: ignore[arg-type]
        for m in meetings
    ]
    every = await agents(svc.db)
    form = send_form("/meetings", agents=agent_options(every), meetings=meetings)
    calendar = await calendar_context(
        svc.db,
        request.query_params,
        viewer_zone(request),
        "/meetings",
        lambda meeting_id: f"/meetings/{meeting_id}",
        every,
        await email_of(svc.db, svc.owner_user_id),
    )
    return render(request, LIST, {"rows": rows, "calendar": calendar} | form)


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
            for name, span, ratio in heard_rows(record.heard_seconds)
        ],
        # One speaker's lines in a row, under their name once.
        "turns": [
            (speaker, list(rows))
            for speaker, rows in groupby(record.transcript, key=lambda r: r.speaker)
        ],
        "clock": {row.id: format_clock(row.at) for row in record.transcript},
        "people": [{"id": name, "name": name} for name in record.people],
        # What the call threw up, a tab per kind, in the order first heard.
        "heard": [
            (found[0].kind, found[0].title, found)
            for found in by_kind(record.moments, attrgetter("kind"))
        ],
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
    agent: Annotated[str, Form()] = "",
) -> Response:
    """Send the bot in, then open its meeting."""
    return await send_and_open(
        svc,
        url,
        bot_name,
        "/meetings",
        lambda meeting_id: f"/meetings/{meeting_id}",
        agent or None,
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
    again, reads the call over again for moments. The Meetings page and Overseer's drawer register the same ones,
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

    @router.post("/{meeting_id}/moments/find", response_class=HTMLResponse)
    async def look_over(svc: scoped, meeting_id: int) -> HTMLResponse:  # type: ignore[valid-type]
        """Read the call over again for moments."""
        with as_http():
            return drawn(await svc.look_over(meeting_id))

    @router.post("/{meeting_id}/moments/{moment_id}/runs", response_class=HTMLResponse)
    async def ask(
        svc: scoped,  # type: ignore[valid-type]
        meeting_id: int,
        moment_id: int,
        action: Annotated[str, Form()],
    ) -> HTMLResponse:
        """Ask an action of something heard in the call."""
        with as_http():
            await svc.ask(meeting_id, moment_id, action)
        return await read(svc, meeting_id)


meeting_routes(router, get_meetings_service, BODY, "/meetings")
