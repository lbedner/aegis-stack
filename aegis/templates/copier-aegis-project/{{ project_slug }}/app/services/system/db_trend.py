"""How each table's rows changed today, for Tables (Database > Tables): the
first count the database health check reads each UTC day (``note``), kept
in the shared cache (Redis when the stack has it, so every process keeps
the same one; this process's memory otherwise, so a restart starts the day
again from then), and the change since (``change``). PostgreSQL's counts
are the planner's estimates, so a change may go down."""

from collections.abc import Mapping
from datetime import datetime

from app.core.cache import get_cache
from app.core.log import logger
from app.core.time import utcnow

KEY = "db_trend:{day}"
KEPT = 2 * 24 * 3600  # a day's first counts outlive it, then go
Baseline = tuple[int, datetime]  # the day's first count, and when it was read


def _key(day: datetime) -> str:
    return KEY.format(day=day.date().isoformat())


async def note(counts: Mapping[str, int], *, now: datetime | None = None) -> None:
    """Keep the day's first count of each table in ``counts`` not kept yet;
    a count below 0 is one the database does not know (a table PostgreSQL
    never analysed). A cache that fails is logged and the health check
    reading the counts goes on."""
    now = now or utcnow()
    key = _key(now)
    # ponytail: read, add, write: two processes at once may each keep their
    # own first count for a table, a moment apart.
    try:
        kept = await get_cache().get(key) or {}
        fresh = {
            name: (count, now.isoformat())
            for name, count in counts.items()
            if count >= 0 and name not in kept
        }
        if fresh:
            await get_cache().set(key, kept | fresh, ttl=KEPT)
    except Exception as exc:  # the cache's backend: Redis, or what it held
        logger.warning(f"Today's table row counts not kept: {exc}")


async def baselines(*, now: datetime | None = None) -> dict[str, Baseline]:
    """Each table's first count today, and when it was read; none where the
    cache fails (logged)."""
    key = _key(now or utcnow())
    try:
        kept = await get_cache().get(key) or {}
    except Exception as exc:  # the cache's backend: Redis, or what it held
        logger.warning(f"Today's table row counts not read: {exc}")
        return {}
    return {
        name: (count, datetime.fromisoformat(at)) for name, (count, at) in kept.items()
    }


def change(count: int | None, baseline: Baseline | None) -> str | None:
    """``count`` against the day's first (``+12 today``, or ``+3 since 14:05
    UTC`` where that was read past the day's first hour: a restart, or a
    table made then); nothing for no change or nothing to compare."""
    if count is None or baseline is None or count < 0:
        return None
    first, at = baseline
    if count == first:
        return None
    since = "today" if at.hour == 0 else f"since {at:%H:%M} UTC"
    return f"{count - first:+,} {since}"
