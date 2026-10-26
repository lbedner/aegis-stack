"""The time windows the app speaks: every range chip row, and every read
that takes a window (an agent's ``aggregate``).

One vocabulary for all of them. A window is a number of days; ``ALL`` is
the "everything" chip, a stand-in no reader is asked to name (``DAYS``).
``since()`` and ``start()`` turn a window into the date, or the moment,
a filter starts at.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from app.core.time import today

# Big enough to mean "no cutoff", small enough to stay a plain int in a
# query string. The API's own windows cap at 3650 days, so a summary
# page's "All" is that ceiling rather than this.
ALL = 9999

# One set of chips, everywhere. The pages differ in what a window means
# (how far back the ledger reads, how far forward the forecast runs), not
# in what it is called, so the row reads the same wherever it appears.
WINDOWS: tuple[tuple[int, str], ...] = (
    (1, "1d"),
    (7, "7d"),
    (14, "14d"),
    (30, "1m"),
    (90, "3m"),
    (365, "1y"),
    (ALL, "All"),
)


# The windows a reader names, by day count; "everything" is no window.
DAYS = tuple(days for days, _ in WINDOWS if days != ALL)


def since(days: int | None) -> date | None:
    """The date a window starts at; ``None`` when it means everything."""
    if days is None or days >= ALL:
        return None
    return today() - timedelta(days=days)


def start(days: int | None) -> datetime | None:
    """The moment a window starts (its first day's midnight), for a
    timestamp column; ``None`` when it means everything."""
    first = since(days)
    return None if first is None else datetime.combine(first, time.min)


def label(days: int | None) -> str:
    """A window as its chip names it (``"7d"``); none is ``"All"``."""
    return dict(WINDOWS)[ALL if days is None else days]
