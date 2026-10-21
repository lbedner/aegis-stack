"""Every agent's calendar as the calendar pages draw it: each meeting in
the viewer's time zone with its agent, the agent's color, and where it
stands (``state``, a code; ``state_label`` says it)."""

from datetime import date, datetime, timedelta
import re
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import as_local, as_stored, utcnow
from app.services.meetings.models import BotAccount, CalendarEvent
from app.services.meetings.service import can_join, status_label, voice, voices

from .queries import between, one, speakers_on

DAY = timedelta(days=1)
# The most days one read covers: a month's six weeks.
MOST_DAYS = 42
# Where a meeting the agent was not (or is no longer) in stands; one it was
# sent into stands as that call's status (``MeetingStatus``).
UPCOMING, MISSED, CANCELLED = "upcoming", "missed", "cancelled"
NO_LINK, CANNOT_JOIN = "no_link", "cannot_join"
# Sent in, and that call since deleted.
SENT = "sent"
LABELS = {CANNOT_JOIN: "Cannot join yet"}
NO_TITLE = "(No title)"


class EventNotFoundError(LookupError):
    """No meeting by that id on any agent's calendar."""


class CalendarEntry(BaseModel):
    """One meeting on an agent's calendar. ``state`` is the call's status
    once the agent was sent in, else one of the codes above; ``color`` is
    the agent's, 1 to the chart ramp, like a speaker's."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int
    agent: str
    color: int
    title: str
    starts_at: datetime
    ends_at: datetime
    url: str | None
    organizer: str | None
    # Every email on the invite, the organizer's first.
    emails: list[str] = []
    state: str
    meeting_id: int | None


class Invitee(BaseModel):
    """One email on an invite, and who it is, when someone who spoke in a
    meeting on its link plainly is (``who_is``), in their color."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    email: str
    name: str | None = None
    color: int | None = None


class CalendarEventDetail(CalendarEntry):
    """One meeting on a calendar opened: what the organizer wrote on it,
    and who is invited."""

    description: str | None = None
    invited: list[Invitee] = []


def who_is(email: str, people: list[str]) -> str | None:
    """The one of ``people`` an email plainly names: its parts all in the
    name (``lisa.atalese``, ``lawrence``), or ending in a surname
    (``drferro``); None when it names nobody, or more than one."""
    # ponytail: the address's local part against names; an alias that
    # names nobody (``ryanf``) stays an email.
    parts = [p for p in re.split(r"[._+-]", email.split("@")[0].lower()) if p]
    local = "".join(parts)

    def names(person: str) -> bool:
        words = [w for w in re.split(r"[\s-]+", person.lower()) if w]
        return bool(parts) and (
            all(p in words for p in parts)
            or (len(words) > 1 and len(words[-1]) > 3 and local.endswith(words[-1]))
        )

    found = [person for person in people if names(person)]
    return found[0] if len(found) == 1 else None


def state_label(state: str) -> str:
    """A state as the pages say it: ``in_call`` -> "In call"."""
    return LABELS.get(state) or status_label(state)


def chosen(every: list[BotAccount], agent: str | None) -> list[BotAccount]:
    """The agents a calendar shows: ``agent`` alone when named, else all."""
    return [a for a in every if agent in (None, a.name)]


async def entries_between(
    db: AsyncSession,
    first: date,
    last: date,
    zone: ZoneInfo,
    wanted: list[BotAccount],
    now: datetime | None = None,
    email: str | None = None,
) -> list[CalendarEntry]:
    """The ``wanted`` agents' meetings (only invites ``email`` is on, when
    given) from ``first`` to ``last``, both days whole in ``zone``;
    earliest first."""
    start = datetime.combine(first, datetime.min.time(), zone)
    end = datetime.combine(last + DAY, datetime.min.time(), zone)
    names = {a.id: a.name for a in wanted if a.id is not None}
    if not names:
        return []
    rows = await between(db, list(names), as_stored(start), as_stored(end))
    stored_now = as_stored(now) if now else utcnow()
    return [
        _entry(row, status, names[row.account_id], zone, stored_now)
        for row, status in rows
        if email is None or email.lower() in row.emails
    ]


async def entry_of(
    db: AsyncSession, event_id: int, zone: ZoneInfo, now: datetime | None = None
) -> CalendarEventDetail:
    """One meeting on any agent's calendar, in ``zone``, with what its
    organizer wrote and who is invited, each named for whoever spoke on its
    link: ``EventNotFoundError`` when there is none by that id."""
    found = await one(db, event_id)
    if found is None:
        raise EventNotFoundError(f"No meeting {event_id} on a calendar")
    row, status, agent = found
    stored_now = as_stored(now) if now else utcnow()
    people = await speakers_on(db, row.url) if row.url else []
    named = {email: who_is(email, people) for email in row.emails}
    colors = voices(name for name in named.values() if name)
    return CalendarEventDetail(
        **_entry(row, status, agent, zone, stored_now).model_dump(),
        description=row.description,
        invited=[
            Invitee(email=email, name=name, color=colors.get(name) if name else None)
            for email, name in named.items()
        ],
    )


def _entry(
    row: CalendarEvent, status: str | None, agent: str, zone: ZoneInfo, now: datetime
) -> CalendarEntry:
    assert row.id is not None
    return CalendarEntry(
        id=row.id,
        agent=agent,
        color=voice(agent),
        title=row.title or NO_TITLE,
        starts_at=as_local(row.starts_at, zone),
        ends_at=as_local(row.ends_at, zone),
        url=row.url,
        organizer=row.organizer,
        emails=row.emails,
        state=_state(row, status, now),
        meeting_id=row.meeting_id,
    )


def _state(row: CalendarEvent, status: str | None, now: datetime) -> str:
    if row.cancelled:
        return CANCELLED
    if status is not None:
        return status
    if row.sent_at is not None:
        return SENT
    if not row.url:
        return NO_LINK
    if not can_join(row.url):
        return CANNOT_JOIN
    return MISSED if row.ends_at <= now else UPCOMING
