"""Every agent's calendar as the calendar pages draw it: each meeting in
the viewer's time zone with its agent, the agent's color, and where it
stands (``state``, a code; ``state_label`` says it)."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import as_local, as_stored, utcnow
from app.services.meetings.models import BotAccount, CalendarEvent
from app.services.meetings.service import can_join, status_label, voice

from .queries import between

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
    state: str
    meeting_id: int | None


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
