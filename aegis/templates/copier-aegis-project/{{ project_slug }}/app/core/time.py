"""One clock for every service.

Timestamp columns across the app are naive UTC: SQLite has no timezone
type and asyncpg rejects aware datetimes against ``timestamp without
time zone``. Every service used to define this helper under its own
name; this is the one they share.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Now, in UTC, as the naive datetime the timestamp columns store."""
    return datetime.now(UTC).replace(tzinfo=None)


def as_stored(value: datetime) -> datetime:
    """A datetime as the timestamp columns store it: naive UTC.

    ``utcnow()``'s counterpart for a value that already exists. An aware
    value is converted to UTC first, so the stored instant is the right one;
    a naive value is taken to be UTC already, the storage convention.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
