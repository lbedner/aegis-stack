"""The meeting calendar on the htmx pages: a month of the agents'
calendars (``domains.calendar.entries``), whole weeks Monday to Sunday in
the viewer's time zone, each agent in its own color, filtered to one agent
by ``?agent=`` and moved a month at a time by ``?month=`` (``2026-10``).
A meeting the agent was sent into opens where the page opens meetings;
on a page with ``details``, any meeting opens its own details instead.
Overseer's shows every invite; the Meetings page's those of its viewer
(``email``), or every one without auth. One month grid draws both
(``pages/meetings/_calendar.html``).
"""

from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import WEEKDAYS, month_days, shift_month
from app.services.meetings.domains.calendar.entries import (
    CANCELLED,
    DAY,
    CalendarEntry,
    chosen,
    entries_between,
)
from app.services.meetings.models import BotAccount

from .meeting_status import state_cell
from .rendering import with_query

MONTH_PARAM, AGENT_PARAM = "month", "agent"


async def calendar_context(
    db: AsyncSession,
    query: Mapping[str, str],
    zone: ZoneInfo,
    page: str,
    opened: Callable[[int], str],
    every: list[BotAccount],
    email: str | None = None,
    details: str | None = None,
) -> dict[str, Any]:
    """The month ``?month=`` names (this one by default) on ``page``, of
    ``every`` agent (one, by ``?agent=``); each sent meeting opening
    ``opened(meeting id)``, or, with ``details`` (a query parameter), each
    meeting opening the page with its id there."""
    today = datetime.now(zone).date()
    month = _month(query.get(MONTH_PARAM)) or today.replace(day=1)
    agent = query.get(AGENT_PARAM) or None
    first, last = month_days(month)
    entries = await entries_between(
        db, first, last, zone, chosen(every, agent), email=email
    )
    by_day: dict[date, list[CalendarEntry]] = defaultdict(list)
    for entry in entries:
        by_day[entry.starts_at.date()].append(entry)

    def at(day: date, who: str | None = agent, **more: str) -> str:
        return with_query(
            page, **{MONTH_PARAM: f"{day:%Y-%m}", AGENT_PARAM: who}, **more
        )

    def detailed(event_id: int) -> str | None:
        return at(month, **{details: str(event_id)}) if details else None

    return {
        "month_label": f"{month:%B %Y}",
        "earlier": at(shift_month(month, -1)),
        "later": at(shift_month(month, 1)),
        "this_month": at(today),
        "agents": [{"label": "All agents", "url": at(month, None), "active": not agent}]
        + [
            {"label": a.name, "url": at(month, a.name), "active": a.name == agent}
            for a in every
        ],
        "weekdays": WEEKDAYS,
        "days": [
            _day(first + n * DAY, month, today, by_day, opened, detailed)
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
    by_day: Mapping[date, list[CalendarEntry]],
    opened: Callable[[int], str],
    detailed: Callable[[int], str | None],
) -> dict[str, Any]:
    return {
        "day": day.isoformat(),
        "number": day.day,
        "label": f"{day:%a %b} {day.day}",
        "today": day == today,
        "outside": day.month != month.month,
        "entries": [_entry(e, opened, detailed) for e in by_day.get(day, [])],
    }


def _entry(
    entry: CalendarEntry,
    opened: Callable[[int], str],
    detailed: Callable[[int], str | None],
) -> dict[str, Any]:
    state = state_cell(entry.state)
    span = f"{entry.starts_at:%H:%M} - {entry.ends_at:%H:%M}"
    return {
        "time": f"{entry.starts_at:%H:%M}",
        "title": entry.title,
        "detail": f"{entry.agent}, {span}, {state['label']}",
        "state": state,
        "cancelled": entry.state == CANCELLED,
        "opens": opened(entry.meeting_id) if entry.meeting_id else None,
        "details": detailed(entry.id),
    }
