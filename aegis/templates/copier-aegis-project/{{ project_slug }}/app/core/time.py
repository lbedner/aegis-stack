"""One clock for every service.

Timestamp columns across the app are naive UTC: SQLite has no timezone
type and asyncpg rejects aware datetimes against ``timestamp without
time zone``. Every service used to define this helper under its own
name; this is the one they share.
"""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def utcnow() -> datetime:
    """Now, in UTC, as the naive datetime the timestamp columns store."""
    return datetime.now(UTC).replace(tzinfo=None)


def today() -> date:
    """Today's date on the same clock: UTC, never the host's local date,
    which runs a day apart from it for part of every evening."""
    return utcnow().date()


def as_stored(value: datetime) -> datetime:
    """A datetime as the timestamp columns store it: naive UTC.

    ``utcnow()``'s counterpart for a value that already exists. An aware
    value is converted to UTC first, so the stored instant is the right one;
    a naive value is taken to be UTC already, the storage convention.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def zone_named(name: str | None) -> ZoneInfo | None:
    """The time zone called ``name`` (``America/New_York``); None when
    there is no such zone."""
    try:
        return ZoneInfo(name) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


def as_local(stored: datetime, zone: ZoneInfo) -> datetime:
    """A stored time (naive UTC, ``as_stored``) in ``zone``."""
    return stored.replace(tzinfo=UTC).astimezone(zone)


# Monday-first weeks, the ISO week the rest of the app reasons in.
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_WEEKS = calendar.Calendar(firstweekday=0)


def month_grid(year: int, month: int) -> list[list[date]]:
    """Weeks of seven dates covering ``year``/``month``.

    Leading and trailing cells belong to the neighbouring months, so every
    week is a full row and a calendar never changes shape mid-month.
    """
    return [list(week) for week in _WEEKS.monthdatescalendar(year, month)]


def month_days(day: date) -> tuple[date, date]:
    """The first and last day a calendar of ``day``'s month shows."""
    weeks = month_grid(day.year, day.month)
    return weeks[0][0], weeks[-1][-1]


def shift_month(anchor: date, delta: int) -> date:
    """``anchor`` moved ``delta`` months, clamped to the 1st.

    Anchored to day 1 on purpose: stepping from 31 Jan would otherwise
    have to invent a 31 Feb, and every strategy for that (clamp, skip,
    overflow) surprises someone.
    """
    index = (anchor.year * 12 + anchor.month - 1) + delta
    return date(index // 12, index % 12 + 1, 1)
