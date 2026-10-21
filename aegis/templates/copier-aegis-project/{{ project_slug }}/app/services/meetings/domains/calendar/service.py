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
from app.core.config import settings
from app.core.log import logger
from app.core.time import as_stored, utcnow
from app.services.meetings.domains.accounts.service import agents, secret_for
from app.services.meetings.domains.bot.login import CALENDAR
from app.services.meetings.domains.notes.queries import delete_in
from app.services.meetings.models import BotAccount, CalendarEvent
from app.services.meetings.service import MeetingsService, can_join

from .feed import CalendarMeeting, meetings_between, read_feed
from .owners import users_by_email
from .queries import drop_unsent_before, due, events_of

# What is kept of a calendar: the month behind and the season ahead.
BEHIND, AHEAD = timedelta(days=30), timedelta(days=90)
Reader = Callable[[str], Awaitable[str]]


async def read_calendars(
    db: AsyncSession, read: Reader = read_feed, now: datetime | None = None
) -> dict[str, int]:
    """Every agent's calendar read again and kept as it is now: a meeting
    moved is moved, one taken off is gone unless the agent was sent into
    it, and one never sent into is dropped once past the month behind. An
    agent with no calendar is skipped, and one whose calendar cannot be
    read keeps what it had. How many meetings each agent read has on it,
    by name."""
    now = now or datetime.now(UTC)
    start, end = now - BEHIND, now + AHEAD
    found = await _read_each(await agents(db), read, start, end)
    if not found:
        return {}
    window = as_stored(start), as_stored(end)
    keys = [m.key for _, meetings in found for m in meetings]
    ids = [agent.id for agent, _ in found if agent.id is not None]
    rows = await events_of(db, ids, *window, keys)
    await drop_unsent_before(db, ids, window[0])
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
            row = by_key.get((agent.id, meeting.key))
            if row is None:
                db.add(CalendarEvent(account_id=agent.id, **meeting.model_dump()))
            else:
                # Unchanged, it is left as it is: no write.
                row.sqlmodel_update(meeting.model_dump())
    gone = [
        row.id
        for row in rows
        if (row.account_id, row.key) not in listed
        and row.sent_at is None
        and window[0] <= row.starts_at <= window[1]
    ]
    await delete_in(db, CalendarEvent.id, gone)
    await db.commit()


async def send_due(db: AsyncSession, now: datetime | None = None) -> list[int]:
    """Send each agent into every meeting on its calendar that starts within
    the minute (or is under way and not over), once, even if that meeting
    is then deleted: with a link the bot can join, not cancelled; none
    while ``MEETINGS_JOIN_FROM_CALENDAR`` is off. Nobody
    pressed send, so each is owned by the first on its invite with an
    account here, the organizer first; nobody's when no one has. The
    meetings sent, by id."""
    # Here, not at the top: the bot loads the browser driver, which only a
    # send needs, not every run of the scheduler.
    from app.services.meetings.domains.bot.run import send_bot

    if not settings.MEETINGS_JOIN_FROM_CALENDAR:
        return []
    now = as_stored(now) if now else utcnow()
    rows = [row for row in await due(db, now) if row.url and can_join(row.url)]
    if not rows:
        return []
    every = await agents(db)
    names = {agent.id: agent.name for agent in every}
    users = await users_by_email(db, (e for row in rows for e in row.emails))
    sent = []
    # ponytail: two runs overlapping could send one twice; a run takes
    # seconds and comes once a minute. A claim on the row if that changes.
    for row in rows:
        owner = next((users[e] for e in row.emails if e in users), None)
        meeting = await send_bot(
            MeetingsService(db, owner), row.url or "", "", names[row.account_id], every
        )
        assert meeting.id is not None
        row.meeting_id, row.sent_at = meeting.id, utcnow()
        db.add(row)
        await db.commit()
        sent.append(meeting.id)
    return sent
