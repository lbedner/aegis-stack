"""Meetings for Overseer, across every owner: the list, the agents the bot
joins as and their calendars, one meeting read in full (its notes, transcript and how long
each speaker was heard) and its threads, which speaker its owner is, its
notes written again, the bot asked to leave, and a meeting deleted; and
who owns what nobody pressed send for: a meeting nobody owns given to
someone, and who an agent's calendar meetings go to when nobody on the
invite has an account here. Reading is the admin's (``get_admin_reader``), a
change an operator's (``get_admin_actor``); an owner's own meetings are
``router``'s."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.core.time import zone_named
from app.services.meetings.deps import as_http, get_every_owners_meetings
from app.services.meetings.domains.accounts.service import (
    AgentRow,
    overview,
    set_default_owner,
)
from app.services.meetings.domains.accounts.service import agents as every_agent
from app.services.meetings.domains.calendar.entries import (
    MOST_DAYS,
    CalendarEntry,
    CalendarEventDetail,
    chosen,
    entries_between,
    entry_of,
)
from app.services.meetings.domains.calendar.owners import Owner, owners
from app.services.meetings.domains.people.participants import give as give_away
from app.services.meetings.domains.threads.service import meeting_threads
from app.services.meetings.models import (
    BotAccount,
    Meeting,
    MeetingRecord,
    ThreadSection,
)
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


@router.get("/agents", response_model=list[AgentRow], dependencies=READ)
async def agents(svc: Every) -> list[AgentRow]:
    """Every agent the bot joins as: whether its sign-in works, and the
    meetings it is in now. Before the meeting routes: not a meeting id."""
    return await overview(svc.db)


class Owned(BaseModel):
    user_id: int | None = None


class Given(BaseModel):
    user_id: int


@router.put("/agents/{name}/owner", response_model=BotAccount, dependencies=CHANGE)
async def agent_owner(name: str, body: Owned, svc: Every) -> BotAccount:
    """Who owns a meeting the agent joins from its calendar when nobody on
    the invite has an account here (none: nobody)."""
    with as_http():
        return await set_default_owner(svc.db, name, body.user_id)


@router.get("/owners", response_model=list[Owner], dependencies=READ)
async def every_owner(svc: Every) -> list[Owner]:
    """Everyone a meeting can be given to, by email; nobody without auth.
    Before the meeting routes: not a meeting id."""
    return await owners(svc.db)


@router.get("/calendar", response_model=list[CalendarEntry], dependencies=READ)
async def calendar(
    svc: Every, first: date, last: date, tz: str = "UTC", agent: str | None = None
) -> list[CalendarEntry]:
    """Every agent's meetings (``agent``'s only, when named) from ``first``
    to ``last``, whole days in time zone ``tz``, up to six weeks. Before the
    meeting routes: not a meeting id."""
    zone = zone_named(tz)
    if zone is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"No time zone {tz}")
    if not 0 <= (last - first).days < MOST_DAYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"From first to last is up to {MOST_DAYS} days",
        )
    wanted = chosen(await every_agent(svc.db), agent)
    return await entries_between(svc.db, first, last, zone, wanted)


@router.get(
    "/calendar/{event_id}", response_model=CalendarEventDetail, dependencies=READ
)
async def calendar_event(
    event_id: int, svc: Every, tz: str = "UTC"
) -> CalendarEventDetail:
    """One meeting on any agent's calendar, in time zone ``tz``: what its
    organizer wrote, and who is invited, named for whoever spoke on its
    link. Before the meeting routes: not a meeting id."""
    zone = zone_named(tz)
    if zone is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"No time zone {tz}")
    with as_http():
        return await entry_of(svc.db, event_id, zone)


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


@router.get(
    "/{meeting_id}/threads", response_model=list[ThreadSection], dependencies=READ
)
async def threads(meeting_id: int, svc: Every) -> list[ThreadSection]:
    """Its commitments, contradictions and positions, with their lines."""
    with as_http():
        return await meeting_threads(svc, meeting_id)


@router.post("/{meeting_id}/owner", response_model=MeetingRecord, dependencies=CHANGE)
async def give(meeting_id: int, body: Given, svc: Every) -> MeetingRecord:
    """Give a meeting nobody owns to someone, its people and notes with it."""
    with as_http():
        await give_away(svc.db, await svc.get(meeting_id), body.user_id)
        return await svc.read(meeting_id)


class Speaker(BaseModel):
    name: str | None = None


@router.post("/{meeting_id}/me", response_model=MeetingRecord, dependencies=CHANGE)
async def set_me(meeting_id: int, body: Speaker, svc: Every) -> MeetingRecord:
    """Which speaker the meeting's owner is (none: nobody); their action
    items follow."""
    with as_http():
        await svc.set_me(meeting_id, body.name or None)
        return await svc.read(meeting_id)


@router.post(
    "/{meeting_id}/notes",
    response_model=MeetingRecord,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=CHANGE,
)
async def write_notes(meeting_id: int, svc: Every) -> MeetingRecord:
    """Write the notes again, over the old ones, in the background."""
    with as_http():
        return await svc.write_notes_again(meeting_id)


@router.delete(
    "/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=CHANGE
)
async def delete(meeting_id: int, svc: Every) -> Response:
    """The meeting and everything kept of it; refused while the bot is in."""
    with as_http():
        await svc.delete(meeting_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
