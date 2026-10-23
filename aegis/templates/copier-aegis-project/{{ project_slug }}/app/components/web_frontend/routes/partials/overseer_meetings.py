"""Actions for the Overseer Meetings page: the bot sent from there, one
meeting in the drawer (live, with which speaker is me and the notes
written again, as the Meetings page has them), the bot asked to leave it,
and the meeting deleted; and one person's guide, its owner's note kept
and the guide written again; and a meeting's threads, loaded into its
drawer; and one series, written again; and one meeting on a calendar;
and who owns what nobody pressed send for: a meeting nobody owns given to
someone, an agent's calendar meetings' default owner. Mounted by ``routes/pages.py`` behind
Overseer's gate; the admin reads and writes every owner's meetings (``Every``), and
a meeting the admin sends is the admin's own (``Mine``).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend import overseer_meetings
from app.components.web_frontend.meeting_agents import agents_context
from app.components.web_frontend.rendering import dialog, fragment, viewer_zone
from app.components.web_frontend.routes.meetings import (
    meeting_context,
    meeting_routes,
    send_and_open,
)
from app.services.meetings.deps import (
    as_http,
    get_every_owners_meetings,
    get_every_owners_people,
    get_every_owners_series,
    get_meetings_service,
)
from app.services.meetings.domains.accounts.service import set_default_owner
from app.services.meetings.domains.calendar.entries import entry_of
from app.services.meetings.domains.people.participants import give as give_away
from app.services.meetings.domains.people.service import PeopleService
from app.services.meetings.domains.series.service import SeriesService
from app.services.meetings.domains.threads.service import meeting_threads
from app.services.meetings.models import GuideRecord, SeriesRecord
from app.services.meetings.service import MeetingsService

PREFIX = overseer_meetings.PARTIALS
router = APIRouter(prefix=PREFIX)
Every = Annotated[MeetingsService, Depends(get_every_owners_meetings)]
Mine = Annotated[MeetingsService, Depends(get_meetings_service)]
People = Annotated[PeopleService, Depends(get_every_owners_people)]
Series = Annotated[SeriesService, Depends(get_every_owners_series)]

DRAWER = "pages/overseer/meetings/_drawer.html"
BODY = "pages/overseer/meetings/_drawer_body.html"
GUIDE = "pages/overseer/meetings/_guide.html"
GUIDE_BODY = "pages/overseer/meetings/_guide_body.html"
THREADS = "pages/overseer/meetings/_threads_body.html"
SERIES = "pages/overseer/meetings/_series_drawer.html"
SERIES_BODY = "pages/overseer/meetings/_series_body.html"
EVENT = "pages/overseer/meetings/_event_drawer.html"
AGENTS = "pages/overseer/meetings/_agents.html"


@router.post("")
async def send(
    svc: Mine,
    url: Annotated[str, Form()],
    bot_name: Annotated[str, Form()] = "",
    agent: Annotated[str, Form()] = "",
) -> Response:
    """Send the bot as the admin, as the agent picked, then open its meeting
    in the drawer."""
    return await send_and_open(
        svc,
        url,
        bot_name,
        PREFIX,
        overseer_meetings.meeting_url,
        agent or None,
    )


@router.get("/{meeting_id}/drawer", response_class=HTMLResponse)
async def drawer(
    request: Request, meeting_id: int, svc: Every, line: int | None = None
) -> Response:
    """The meeting, at ``line`` (a search hit's) when given."""
    context = await meeting_context(svc, meeting_id) | {"prefix": PREFIX}
    context |= await overseer_meetings.owner_context(svc)
    return dialog(request, DRAWER, **context, hit_line=line)


# The drawer's live part: re-read while the bot is in or the notes are being
# written; the bot asked to leave, which speaker the owner is, the notes
# written again, the same routes as the Meetings page's.
meeting_routes(
    router, get_every_owners_meetings, BODY, PREFIX, overseer_meetings.owner_context
)


@router.post("/{meeting_id}/owner", response_class=HTMLResponse)
async def give(
    meeting_id: int, svc: Every, user_id: Annotated[int, Form()]
) -> HTMLResponse:
    """Give a meeting nobody owns to someone, its people and notes with it."""
    with as_http():
        await give_away(svc.db, await svc.get(meeting_id), user_id)
    context = await meeting_context(svc, meeting_id) | {"prefix": PREFIX}
    context |= await overseer_meetings.owner_context(svc)
    return HTMLResponse(fragment(BODY, **context))


@router.post("/agents/{name}/owner", response_class=HTMLResponse)
async def agent_owner(
    name: str, svc: Every, user_id: Annotated[str, Form()] = ""
) -> HTMLResponse:
    """Who owns a meeting the agent joins from its calendar when nobody on
    the invite has an account here (blank: nobody)."""
    with as_http():
        await set_default_owner(svc.db, name, int(user_id) if user_id else None)
    context = await agents_context(svc.db, overseer_meetings.meeting_url)
    return HTMLResponse(fragment(AGENTS, **context, partials=PREFIX))


@router.get("/{meeting_id}/threads", response_class=HTMLResponse)
async def threads(meeting_id: int, svc: Every) -> HTMLResponse:
    """The meeting's threads, for the drawer's slot."""
    with as_http():
        sections = await meeting_threads(svc, meeting_id)
    context = overseer_meetings.threads_context(sections, meeting_id)
    return HTMLResponse(fragment(THREADS, **context))


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


@router.get("/people/{guide_id}/drawer", response_class=HTMLResponse)
async def guide(request: Request, guide_id: int, svc: People) -> Response:
    with as_http():
        record = await svc.read(guide_id)
    return dialog(request, GUIDE, **overseer_meetings.guide_context(record))


def _guide_body(record: GuideRecord) -> HTMLResponse:
    return HTMLResponse(fragment(GUIDE_BODY, **overseer_meetings.guide_context(record)))


@router.get("/people/{guide_id}/body", response_class=HTMLResponse)
async def guide_body(guide_id: int, svc: People) -> HTMLResponse:
    """The guide's live part, re-read while it is being written."""
    with as_http():
        return _guide_body(await svc.read(guide_id))


@router.post("/people/{guide_id}/note", response_class=HTMLResponse)
async def guide_note(
    guide_id: int, svc: People, note: Annotated[str, Form()] = ""
) -> HTMLResponse:
    """The owner's note on the person; blank clears it."""
    with as_http():
        return _guide_body(await svc.set_note(guide_id, note))


@router.post("/people/{guide_id}/guide", response_class=HTMLResponse)
async def write_guide(guide_id: int, svc: People) -> HTMLResponse:
    """Write the guide again from every meeting, in the background."""
    with as_http():
        return _guide_body(await svc.write_again(guide_id))


@router.get("/calendar/{event_id}/drawer", response_class=HTMLResponse)
async def calendar_event(request: Request, event_id: int, svc: Every) -> Response:
    """One meeting on any agent's calendar, in the viewer's time zone."""
    with as_http():
        entry = await entry_of(svc.db, event_id, viewer_zone(request))
    return dialog(request, EVENT, **overseer_meetings.event_context(entry))


@router.get("/series/{series_id}/drawer", response_class=HTMLResponse)
async def series(request: Request, series_id: int, svc: Series) -> Response:
    with as_http():
        record = await svc.read(series_id)
    return dialog(request, SERIES, **overseer_meetings.series_context(record))


def _series_body(record: SeriesRecord) -> HTMLResponse:
    context = overseer_meetings.series_context(record)
    return HTMLResponse(fragment(SERIES_BODY, **context))


@router.get("/series/{series_id}/body", response_class=HTMLResponse)
async def series_body(series_id: int, svc: Series) -> HTMLResponse:
    """The series' live part, re-read while it is being written."""
    with as_http():
        return _series_body(await svc.read(series_id))


@router.post("/series/{series_id}/write", response_class=HTMLResponse)
async def write_series(series_id: int, svc: Series) -> HTMLResponse:
    """Write the series again from its latest meetings, in the background."""
    with as_http():
        return _series_body(await svc.write_again(series_id))
