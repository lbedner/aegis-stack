"""What each part of the app holds, as figures an agent reads: counts and
sums grouped by labels, never a row or a field's value, and app-wide
(never one owner's), so one cached answer serves every reader.

Each part declares its own in ``app/services/<part>/aggregates.py`` as
``AGGREGATES``, a tuple of ``Aggregate``, found by that module's name
(``app.core.discovery``), as its scheduled jobs are. Each reads its data
in the session it is given, once per window it is asked for; the shared
cache serves the same answer for ``KEEP`` seconds, so a burst of questions
costs one query. A window is one of the app's (``app.core.ranges``).
"""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.core import ranges
from app.core.cache import CACHE_ERRORS, get_cache
from app.core.discovery import declared_by
from app.core.key_family import KeyFamily
from app.core.log import logger

KEEP = 60  # seconds the same figures are served from the cache
KEY = "aggregate:{name}:{days}"
REDIS_KEYS = (
    KeyFamily(
        KEY.format(name="*", days="*"),
        "string",
        "Aggregates",
        "Each aggregate's figures for a window, kept a minute",
        "Aggregates",
        db="CACHE_REDIS_DB",
    ),
)


@dataclass(frozen=True)
class Aggregate:
    """What one part's data says about itself: ``name`` within its part,
    ``about`` the question it answers, ``read`` its figures (a frozen
    ``FIGURES`` model) from a session, over the last ``days`` (None: all of
    it)."""

    name: str
    about: str
    read: Callable[[Any, int | None], Awaitable[BaseModel]]


def declared() -> dict[str, Aggregate]:
    """Every part's aggregates, by ``<part>.<name>``. A name claimed twice
    is an error, not a silent winner: the second would hide the first."""
    import app.services as services

    found: dict[str, Aggregate] = {}
    for part, declared_here in declared_by(services, "aggregates", "AGGREGATES"):
        for one in declared_here:
            name = f"{part}.{one.name}"
            if name in found:
                raise ValueError(f"two aggregates claim {name!r}")
            found[name] = one
    return found


def window(days: int | None) -> int | None:
    """``days`` as one of the app's windows (``ranges.DAYS``), None for all
    of it (``ALL``, or none given); any other is refused, naming them."""
    if days is None or days == ranges.ALL:
        return None
    if days not in ranges.DAYS:
        known = ", ".join(map(str, ranges.DAYS))
        raise ValueError(f"No window of {days} days; the windows: {known}, or none")
    return days


async def read(name: str, days: int | None = None) -> BaseModel:
    """``name``'s figures over the last ``days``: from the cache when the
    same window was read in the last ``KEEP`` seconds. A cache that does
    not answer costs the query, never the read."""
    found = declared()
    if name not in found:
        raise ValueError(f"No aggregate {name!r}; known: {', '.join(sorted(found))}")
    days = window(days)
    key = KEY.format(name=name, days=days or "all")
    try:
        kept = await get_cache().get(key)
    except CACHE_ERRORS as exc:
        logger.warning("Aggregate read uncached", aggregate=name, error=str(exc))
        return await _figures(found[name], days)
    if kept is not None:
        return kept
    figures = await _figures(found[name], days)
    try:
        await get_cache().set(key, figures, ttl=KEEP)
    except CACHE_ERRORS as exc:
        logger.warning("Aggregate not kept", aggregate=name, error=str(exc))
    return figures


async def _figures(one: Aggregate, days: int | None) -> BaseModel:
    async with _session() as session:
        return await one.read(session, days)


def _session() -> AbstractAsyncContextManager[Any]:
    """A database session (imported when read: a stack without a database
    declares no aggregate that needs one)."""
    from app.core.db import get_async_session

    return get_async_session()
