"""The meeting calendar on the htmx pages: a month of every agent's
calendar (``domains.calendar.entries``), whole weeks Monday to Sunday in
the viewer's time zone, each agent in its own color, filtered to one agent
by ``?agent=`` and moved a month at a time by ``?month=`` (``2026-10``).
A meeting the agent was sent into opens where the page opens meetings.
Overseer's shows every invite; the Meetings page's those of its viewer
(``email``), or every one without auth. One month grid draws both
(``pages/meetings/_calendar.html``).
"""

from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.accounts.service import agents
from app.services.meetings.domains.calendar.entries import (
    CANCELLED,
    CANNOT_JOIN,
    DAY,
    MISSED,
    UPCOMING,
    CalendarEntry,
    entries_between,
    month_days,
)
from app.services.meetings.service import status_label

from .rendering import status_cell, with_query
from .routes.meetings import TONES as MEETING_TONES

MONTH_PARAM, AGENT_PARAM = "month", "agent"
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
TONES = {status_label(s): tone for s, tone in MEETING_TONES.items()} | {
    UPCOMING: "accent",
    MISSED: "warn",
    CANNOT_JOIN: "warn",
}


async def calendar_context(
    db: AsyncSession,
    query: Mapping[str, str],
    zone: ZoneInfo,
    page: str,
    opened: Callable[[int], str],
    target: str,
    email: str | None = None,
    opens_here: bool = False,
) -> dict[str, Any]:
    """The month ``?month=`` names (this one by default) on ``page``, moved
    by swapping ``target``; each sent meeting opening ``opened(meeting
    id)``, swapped into ``target`` too when it ``opens_here`` (a drawer on
    this page)."""
    today = datetime.now(zone).date()
    month = _month(query.get(MONTH_PARAM)) or today.replace(day=1)
    agent = query.get(AGENT_PARAM) or None
    every = await agents(db)
    first, last = month_days(month)
    entries = await entries_between(
        db, first, last, zone, agent, every=every, email=email
    )

    def at(day: date, who: str | None = agent) -> str:
        return with_query(page, **{MONTH_PARAM: f"{day:%Y-%m}", AGENT_PARAM: who})

    return {
        "target": target,
        "opens_here": opens_here,
        "month_label": f"{month:%B %Y}",
        "earlier": at(month - DAY),
        "later": at(month + timedelta(days=31)),
        "this_month": at(today),
        "agents": [{"label": "All agents", "url": at(month, None), "active": not agent}]
        + [
            {"label": a.name, "url": at(month, a.name), "active": a.name == agent}
            for a in every
        ],
        "weekdays": WEEKDAYS,
        "days": [
            _day(first + n * DAY, month, today, entries, opened)
            for n in range((last - first).days + 1)
        ],
    }


def _month(value: str | None) -> date | None:
    """``2026-10`` as its first day; None for anything else."""
    try:
        return date.fromisoformat(f"{value}-01") if value else None
    except ValueError:
        return None


def _day(
    day: date,
    month: date,
    today: date,
    entries: list[CalendarEntry],
    opened: Callable[[int], str],
) -> dict[str, Any]:
    return {
        "day": day.isoformat(),
        "number": day.day,
        "label": f"{day:%a %b} {day.day}",
        "today": day == today,
        "outside": day.month != month.month,
        "entries": [_entry(e, opened) for e in entries if e.starts_at.date() == day],
    }


def _entry(entry: CalendarEntry, opened: Callable[[int], str]) -> dict[str, Any]:
    span = f"{entry.starts_at:%H:%M} - {entry.ends_at:%H:%M}"
    return {
        "time": f"{entry.starts_at:%H:%M}",
        "title": entry.title or "(No title)",
        "detail": f"{entry.agent}, {span}, {entry.state}",
        "color": entry.color,
        "state": status_cell(entry.state, TONES.get(entry.state, "muted")),
        "cancelled": entry.state == CANCELLED,
        "opens": opened(entry.meeting_id) if entry.meeting_id else None,
    }
