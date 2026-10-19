"""Every agent's calendar as the calendar pages draw it: the days a month
covers (``month_days``), each meeting on them in the viewer's time zone
with its agent, the agent's color, and where it stands."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import as_stored, utcnow
from app.services.meetings.domains.accounts.service import agents
from app.services.meetings.models import BotAccount, CalendarEvent
from app.services.meetings.service import can_join, status_label, voice

from .queries import between

DAY = timedelta(days=1)
# The most days one read covers: a month's six weeks.
MOST_DAYS = 42
UPCOMING, MISSED, CANCELLED = "Upcoming", "Missed", "Cancelled"
NO_LINK, CANNOT_JOIN = "No link", "Cannot join yet"
# Sent in, and that call since deleted.
SENT = "Sent"


class CalendarEntry(BaseModel):
    """One meeting on an agent's calendar. ``state`` is the call's status
    once the agent was sent in, else one of the states above; ``color`` is
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
    state: str
    meeting_id: int | None


def month_days(day: date) -> tuple[date, date]:
    """The days a calendar of ``day``'s month shows: Monday of its first
    week to Sunday of its last."""
    first = day.replace(day=1)
    following = (first + timedelta(days=31)).replace(day=1)
    last = following - DAY
    return first - first.weekday() * DAY, last + (6 - last.weekday()) * DAY


async def entries_between(
    db: AsyncSession,
    first: date,
    last: date,
    zone: ZoneInfo,
    agent: str | None = None,
    now: datetime | None = None,
    every: list[BotAccount] | None = None,
    email: str | None = None,
) -> list[CalendarEntry]:
    """Every agent's meetings (only ``agent``'s, when named; of ``every``,
    the agents, when read already; only invites ``email`` is on, when
    given) from ``first`` to ``last``, both days whole in ``zone``;
    earliest first."""
    start = datetime.combine(first, datetime.min.time(), zone)
    end = datetime.combine(last + DAY, datetime.min.time(), zone)
    wanted = [a for a in every or await agents(db) if agent in (None, a.name)]
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


def _entry(
    row: CalendarEvent, status: str | None, agent: str, zone: ZoneInfo, now: datetime
) -> CalendarEntry:
    assert row.id is not None
    return CalendarEntry(
        id=row.id,
        agent=agent,
        color=voice(agent),
        title=row.title,
        starts_at=_local(row.starts_at, zone),
        ends_at=_local(row.ends_at, zone),
        url=row.url,
        organizer=row.organizer,
        state=_state(row, status, now),
        meeting_id=row.meeting_id,
    )


def _local(stored: datetime, zone: ZoneInfo) -> datetime:
    """A stored (naive UTC) time in ``zone``."""
    return stored.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone)


def _state(row: CalendarEvent, status: str | None, now: datetime) -> str:
    if row.cancelled:
        return CANCELLED
    if status is not None:
        return status_label(status)
    if row.sent_at is not None:
        return SENT
    if not row.url:
        return NO_LINK
    if not can_join(row.url):
        return CANNOT_JOIN
    return MISSED if row.ends_at <= now else UPCOMING
