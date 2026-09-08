"""Shared helpers for the insights service."""

from __future__ import annotations

from datetime import date, datetime, timedelta


def day_start(day: date | None) -> datetime | None:
    """Midnight opening ``day``; None passes through as "no bound"."""
    return None if day is None else datetime.combine(day, datetime.min.time())


def day_end(day: date | None) -> datetime | None:
    """The last instant of ``day``; None passes through as "no bound"."""
    return None if day is None else datetime.combine(day, datetime.max.time())


def today() -> datetime:
    """Today at midnight, local and naive: the day key the collectors and
    the dashboard windows agree on."""
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def range_cutoffs(days: int) -> tuple[datetime, datetime]:
    """(cutoff, prev_cutoff) for a trailing window: ``cutoff`` opens the
    current period, ``prev_cutoff`` the equal-length period before it.
    ``days >= 9999`` means all time."""
    now = today()
    if days >= 9999:
        return datetime(2000, 1, 1), datetime(2000, 1, 1)
    cutoff = now - timedelta(days=days)
    return cutoff, cutoff - timedelta(days=days)
