"""Caps that hold across processes: how many a window may start
(``Budget``), and how many may run at once (``Slots``).

Counted on the shared cache (``CacheService.count``): with Redis, every
webserver process and replica counts into one number; without it, each
process caps itself. The key a caller passes is its pool (an IP, a visitor,
``"guests"``), so traffic counted under one key never spends another's.

Mechanism only: what is capped, and how much, is the caller's, read from
the two settings it names on every check (tunable while the app runs, as
``RateLimiter`` reads its own). A cap of 0 is off.

Fails open: a cache that cannot be reached lets the request through with a
warning. A cache blip must not lock everyone out.
"""

from __future__ import annotations

import time

from app.core.cache import CACHE_ERRORS, get_cache
from app.core.config import settings
from app.core.key_family import KeyFamily
from app.core.log import logger

# ponytail: a slot count lapses this long after its first take, so a slot a
# crashed process never released is gone by then; a pool busy past it
# under-counts until its holders end. Holder sets if that ever matters.
SLOT_SECONDS = 6 * 3600

REDIS_KEYS = (
    KeyFamily(
        "limit:*",
        "string",
        "Limits",
        "What a capped pool used this window, or holds right now",
        "Limits",
        db="CACHE_REDIS_DB",
        columns=("Pool", "Used"),
        holds="count",
    ),
)


async def _count(key: str, by: int, ttl: int) -> int | None:
    """``by`` added at ``key``, or None when the cache cannot be reached."""
    try:
        return await get_cache().count(key, by, ttl)
    except CACHE_ERRORS as exc:
        logger.warning("limit not counted; letting it through", key=key, error=str(exc))
        return None


class Budget:
    """At most ``cap_setting`` takes per key in each ``window_setting``
    seconds, counted in fixed windows."""

    def __init__(self, name: str, cap_setting: str, window_setting: str) -> None:
        self.name = name
        self.cap_setting = cap_setting
        self.window_setting = window_setting

    @property
    def window_seconds(self) -> int:
        return int(getattr(settings, self.window_setting))

    async def take(self, key: str) -> bool:
        """Count one against ``key``'s pool; whether it was under the cap."""
        cap: int = getattr(settings, self.cap_setting)
        if cap <= 0:
            return True
        window = self.window_seconds
        bucket = int(time.time() // window)
        used = await _count(f"limit:{self.name}:{key}:{bucket}", 1, window)
        return used is None or used <= cap


class Slots:
    """At most ``cap_setting`` held at once per key; each ``take`` that
    returned True is ``release``d once, however its work ended."""

    def __init__(self, name: str, cap_setting: str) -> None:
        self.name = name
        self.cap_setting = cap_setting

    def _key(self, key: str) -> str:
        return f"limit:{self.name}:{key}"

    async def take(self, key: str) -> bool:
        """Hold one of ``key``'s slots, if one is free."""
        cap: int = getattr(settings, self.cap_setting)
        if cap <= 0:
            return True
        held = await _count(self._key(key), 1, SLOT_SECONDS)
        if held is None or held <= cap:
            return True
        await _count(self._key(key), -1, SLOT_SECONDS)
        return False

    async def release(self, key: str) -> None:
        """Free a slot ``take`` gave; a count that lapsed meanwhile is
        floored at zero rather than run negative."""
        held = await _count(self._key(key), -1, SLOT_SECONDS)
        if held is not None and held < 0:
            await _count(self._key(key), -held, SLOT_SECONDS)
