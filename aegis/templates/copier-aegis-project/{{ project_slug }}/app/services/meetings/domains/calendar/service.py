"""Each agent's calendar kept as rows, read again every minute
(``scheduled_jobs``): what it is invited to, so it is sent on time and
the calendar is drawn without reading every feed. An agent's calendar is
its Google Calendar's secret iCal address, kept under ``CALENDAR`` (the
first agent's) or ``CALENDAR__<NAME>``."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import secrets
from app.core.log import logger
from app.core.time import as_stored, utcnow
from app.services.meetings.domains.accounts.service import agents, secret_for
from app.services.meetings.domains.notes.queries import delete_in
from app.services.meetings.login import CALENDAR
from app.services.meetings.models import BotAccount, CalendarEvent

from .feed import CalendarMeeting, meetings_between, read_feed
from .queries import events_of

# What is kept of a calendar: the month behind and the season ahead.
BEHIND, AHEAD = timedelta(days=30), timedelta(days=90)
Reader = Callable[[str], Awaitable[str]]


async def read_calendars(
    db: AsyncSession, read: Reader = read_feed, now: datetime | None = None
) -> dict[str, int]:
    """Every agent's calendar read again and kept as it is now: a meeting
    moved is moved, one taken off is gone unless the agent was sent into
    it. An agent with no calendar is skipped, and one whose calendar cannot
    be read keeps what it had. How many meetings each agent read has on
    it, by name."""
    now = now or datetime.now(UTC)
    start, end = now - BEHIND, now + AHEAD
    found = await _read_each(await agents(db), read, start, end)
    if not found:
        return {}
    window = as_stored(start), as_stored(end)
    keys = [m.key for _, meetings in found for m in meetings]
    ids = [agent.id for agent, _ in found if agent.id is not None]
    rows = await events_of(db, ids, *window, keys)
    await _keep(db, found, rows, window)
    return {agent.name: len(meetings) for agent, meetings in found}


async def _read_each(
    every: list[BotAccount], read: Reader, start: datetime, end: datetime
) -> list[tuple[BotAccount, list[CalendarMeeting]]]:
    """Each agent with a calendar, and the meetings on it; at once."""
    urls = await secrets.get_many(*(secret_for(CALENDAR, e.name) for e in every))
    have = [(e, url) for e in every if (url := urls[secret_for(CALENDAR, e.name)])]
    feeds = await asyncio.gather(
        *(read(url) for _, url in have), return_exceptions=True
    )
    found = []
    for (agent, _), feed in zip(have, feeds, strict=True):
        if isinstance(feed, BaseException):
            # The error's text names the address, a secret: only its type.
            logger.warning(
                "Agent calendar unreadable", agent=agent.name, error=type(feed).__name__
            )
            continue
        found.append((agent, meetings_between(feed, start, end)))
    return found


async def _keep(
    db: AsyncSession,
    found: list[tuple[BotAccount, list[CalendarMeeting]]],
    rows: list[CalendarEvent],
    window: tuple[datetime, datetime],
) -> None:
    by_key = {(row.account_id, row.key): row for row in rows}
    listed = set()
    for agent, meetings in found:
        assert agent.id is not None
        for meeting in meetings:
            listed.add((agent.id, meeting.key))
            row = by_key.get((agent.id, meeting.key)) or CalendarEvent(
                account_id=agent.id, **meeting.model_dump()
            )
            row.sqlmodel_update(meeting.model_dump())
            row.read_at = utcnow()
            db.add(row)
    gone = [
        row.id
        for row in rows
        if (row.account_id, row.key) not in listed
        and row.meeting_id is None
        and window[0] <= row.starts_at <= window[1]
    ]
    await delete_in(db, CalendarEvent.id, gone)
    await db.commit()
