"""Where the live charts' points live (``app.core.series`` reads and writes
them): Redis when the stack has it, so every process reads the same
history; this process's memory otherwise.

Two shapes, each for what it holds:

- The raw hour: a sorted set a series, scored by time, so a read takes a
  window by time and each write trims what has aged out (``append``,
  ``points``).
- A history tier: a list a series, appended in time order and cut to its
  length (``push``, ``recent``). A tier's points come a step apart, so a
  length is a span; and a list of short entries costs a few bytes a point,
  where a sorted set costs over a hundred, which is what a week costs.

Each series is listed in its sampler's index set, so a read never scans
the keyspace.
"""

from bisect import bisect_left, bisect_right
from operator import itemgetter
import time
from typing import Any

Points = dict[str, list[tuple[float, float]]]


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _point(member: Any) -> tuple[float, float]:
    """A point as stored: ``"<at>:<value>"``."""
    at, value = _text(member).split(":")
    return float(at), float(value)


class SeriesStore:
    """The live charts' points: Redis when ``redis_url`` is given, a dict
    of this process's otherwise."""

    def __init__(self, *, redis_url: str | None = None, redis_db: int = 1) -> None:
        self._redis: Any = None
        # Each series' points, oldest first, and when it lapses.
        self._store: dict[str, tuple[list[tuple[float, float]], float]] | None = None
        if redis_url:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                redis_url, db=redis_db, socket_timeout=2, socket_connect_timeout=2
            )
        else:
            self._store = {}

    async def append(
        self, points: dict[str, float], *, at: float, keep_seconds: int, index: str
    ) -> None:
        """A point at ``at`` on each raw series in ``points``, dropping the
        ones older than ``keep_seconds`` before it, in one round trip."""
        if self._redis is not None:
            pipe = self._redis.pipeline(transaction=False)
            for key, value in points.items():
                pipe.zadd(key, {f"{at}:{value}": at})
                pipe.zremrangebyscore(key, "-inf", at - keep_seconds)
                pipe.expire(key, keep_seconds)
            self._list(pipe, index, points, keep_seconds)
            await pipe.execute()
            return
        for key, value in points.items():
            kept = self._kept(key)
            # Points arrive in time order: drop the stale ones from the front.
            del kept[: bisect_right(kept, at - keep_seconds, key=itemgetter(0))]
            kept.append((at, value))
            self._lapse(key, kept, keep_seconds)

    async def points(
        self, prefix: str, *, since: float, index: str, ending: tuple[str, ...] = ()
    ) -> Points:
        """Every raw series under ``prefix`` (ending with one of ``ending``,
        given any), its points from ``since`` on, oldest first."""
        if self._redis is None:
            return self._read(prefix, since, ending)
        keys = await self._listed(prefix, index, ending)
        pipe = self._redis.pipeline(transaction=False)
        for key in keys:
            pipe.zrangebyscore(key, since, "+inf")
        found = dict(zip(keys, await pipe.execute(), strict=True))
        return await self._kept_listed(index, found, since)

    async def push(
        self,
        points: dict[str, float],
        *,
        at: float,
        length: int,
        keep_seconds: int,
        index: str,
    ) -> None:
        """A point at ``at`` on each tier series in ``points``, keeping its
        newest ``length``, in one round trip. Points come in time order."""
        if self._redis is not None:
            pipe = self._redis.pipeline(transaction=False)
            for key, value in points.items():
                pipe.rpush(key, f"{int(at)}:{value:.6g}")
                pipe.ltrim(key, -length, -1)
                pipe.expire(key, keep_seconds)
            self._list(pipe, index, points, keep_seconds)
            await pipe.execute()
            return
        for key, value in points.items():
            kept = self._kept(key)
            kept.append((at, value))
            del kept[:-length]
            self._lapse(key, kept, keep_seconds)

    async def recent(
        self, prefix: str, *, since: float, index: str, ending: tuple[str, ...] = ()
    ) -> Points:
        """Every tier series under ``prefix`` (ending with one of ``ending``,
        given any), its points from ``since`` on, oldest first."""
        if self._redis is None:
            return self._read(prefix, since, ending)
        keys = await self._listed(prefix, index, ending)
        pipe = self._redis.pipeline(transaction=False)
        for key in keys:
            pipe.lrange(key, 0, -1)
        found = dict(zip(keys, await pipe.execute(), strict=True))
        return await self._kept_listed(index, found, since)

    @staticmethod
    def _list(pipe: Any, index: str, points: dict[str, float], keep: int) -> None:
        if points:
            pipe.sadd(index, *points)
            pipe.expire(index, keep)

    async def _listed(
        self, prefix: str, index: str, ending: tuple[str, ...]
    ) -> list[str]:
        """The series ``index`` lists under ``prefix`` (and ``ending``)."""
        listed = sorted(_text(k) for k in await self._redis.smembers(index))
        return [
            key
            for key in listed
            if key.startswith(prefix) and (not ending or key.endswith(ending))
        ]

    async def _kept_listed(
        self, index: str, found: dict[str, list[Any]], since: float
    ) -> Points:
        """Each series' points from ``since`` on; a series gone since it
        was listed (expired) is taken off its index."""
        gone = [key for key, members in found.items() if not members]
        if gone:
            await self._redis.srem(index, *gone)
        read = {key: [_point(m) for m in members] for key, members in found.items()}
        kept = {
            key: [p for p in points if p[0] >= since] for key, points in read.items()
        }
        return {key: points for key, points in kept.items() if points}

    def _kept(self, key: str) -> list[tuple[float, float]]:
        assert self._store is not None
        kept, lapses = self._store.get(key, ([], 0.0))
        return kept if lapses > time.time() else []

    def _lapse(self, key: str, kept: list[tuple[float, float]], keep: int) -> None:
        assert self._store is not None
        self._store[key] = (kept, time.time() + keep)

    def _read(self, prefix: str, since: float, ending: tuple[str, ...]) -> Points:
        assert self._store is not None
        now = time.time()
        found = {
            key: kept[bisect_left(kept, since, key=itemgetter(0)) :]
            for key, (kept, lapses) in list(self._store.items())
            if key.startswith(prefix)
            and lapses > now
            and (not ending or key.endswith(ending))
        }
        return {key: points for key, points in found.items() if points}


def _build() -> SeriesStore:
    """The process's store, on the shared cache's Redis database where the
    stack has Redis (settings read here, not at import)."""
    from app.core.config import settings

    return SeriesStore(
        redis_url=getattr(settings, "redis_url_effective", None),
        redis_db=getattr(settings, "CACHE_REDIS_DB", 1),
    )


store = _build()


def get_store() -> SeriesStore:
    return store
