"""
Application cache service.

Process-shared TTL cache. Backed by Redis in production (so the
webserver, the scheduler, the CLI, and any future worker all read
and write to the same store), and by an in-memory dict in tests
and when no Redis URL is configured.

Async-first API
---------------
All ops (`get`, `set`, `invalidate`, `invalidate_prefix`, `clear`)
are coroutines. Callers ``await`` each call. Production callers are
already async (FastAPI handlers, collector loops, CLI entrypoints
under ``asyncio.run``), so the cost is just one ``await`` token per
callsite — and the win is not blocking the event loop on Redis I/O.

Two-backend design
------------------
* ``redis_url is None`` → in-memory ``dict[str, (value, expires_at)]``.
  Tests that do ``CacheService()`` directly stay self-contained, no
  Redis server needed.
* ``redis_url`` set → ``redis.asyncio.Redis``, values pickled. The
  module-level singleton uses this path.

Why pickle
----------
Cached values are arbitrary Python objects (Pydantic models, dicts,
lists). Pickle round-trips losslessly with no per-model serialisation
contract. The cache is process-trusted (we put values in, we pull
them out), so the unsafe-unpickle attack surface doesn't apply.

Why a separate logical DB
-------------------------
``CACHE_REDIS_DB`` keeps this cache off the queue DB where arq's
jobs live. ``cache.clear()`` (FLUSHDB on the cache DB) can't
accidentally take down the worker, and arq purges can't blow away
view cache.
"""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from operator import itemgetter
import pickle
import time
from typing import Any, NamedTuple

# Entries the Overseer's Cache view reads before sampling, like the Redis
# keyspace map.
INSPECT_LIMIT = 10_000


class CacheEntry(NamedTuple):
    key: str
    size: int  # bytes as stored (pickled)
    ttl: float  # seconds left


@dataclass
class CacheStats:
    """Hits, misses and writes for one key family, in this process."""

    hits: int = 0
    misses: int = 0
    sets: int = 0


def family(key: str) -> str:
    """A key's family: its first two ``:``-separated parts
    (``insights:project:7`` is ``insights:project``)."""
    return ":".join(key.split(":")[:2])


class CacheService:
    """Async TTL cache with pluggable backend (Redis or in-memory dict).

    Default TTL of 5 min matches the original template default;
    callers can override per-set when needed.
    """

    def __init__(
        self,
        default_ttl: int = 300,
        *,
        redis_url: str | None = None,
        redis_db: int = 1,
    ) -> None:
        self._default_ttl = default_ttl
        self._stats: dict[str, CacheStats] = {}
        self._redis: Any = None
        self._store: dict[str, tuple[Any, float]] | None = None
        if redis_url:
            # Imported lazily so the dict-only path doesn't carry the
            # redis dependency at import time (tests that hit
            # ``CacheService()`` directly stay fast).
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                redis_url,
                db=redis_db,
                decode_responses=False,  # we store bytes (pickled)
                # Hard timeouts so a flapping Redis can't wedge a
                # webserver request behind a stuck cache call.
                socket_timeout=2,
                socket_connect_timeout=2,
            )
        else:
            self._store = {}

    # ----- backend-agnostic ops -----

    async def get(self, key: str) -> Any | None:
        """Return a cached value, or None if missing/expired."""
        value = await self._lookup(key)
        counts = self._stats.setdefault(family(key), CacheStats())
        if value is None:
            counts.misses += 1
        else:
            counts.hits += 1
        return value

    async def _lookup(self, key: str) -> Any | None:
        if self._redis is not None:
            blob = await self._redis.get(key)
            if blob is None:
                return None
            return pickle.loads(blob)
        assert self._store is not None
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.time() > expires_at:
            del self._store[key]
            return None
        return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store a value with TTL (seconds). Uses default_ttl if not specified.

        ``ttl <= 0`` means "don't cache this value". Both backends honor
        this the same way: if the key already exists, it's deleted; the
        new value is not written. Without this guard, Redis would floor
        to ``ex=1`` (the smallest allowed expiry) and the dict backend
        would write an instantly-stale entry that lingers until the next
        read — both surprising behaviors for callers that pass ``ttl=0``
        to mean "invalidate".
        """
        ttl_eff = ttl if ttl is not None else self._default_ttl
        if ttl_eff <= 0:
            if self._redis is not None:
                await self._redis.delete(key)
                return
            assert self._store is not None
            self._store.pop(key, None)
            return
        self._stats.setdefault(family(key), CacheStats()).sets += 1
        if self._redis is not None:
            blob = pickle.dumps(value)
            await self._redis.set(key, blob, ex=ttl_eff)
            return
        assert self._store is not None
        self._store[key] = (value, time.time() + ttl_eff)

    @property
    def backend_name(self) -> str:
        return "redis" if self._redis is not None else "memory"

    def stats(self) -> dict[str, CacheStats]:
        """Hits, misses and writes per key family since this process
        started. Per process: with Redis the entries are shared, the
        counts are not."""
        return dict(self._stats)

    async def entries(
        self, limit: int = INSPECT_LIMIT
    ) -> tuple[list[CacheEntry], bool]:
        """Up to ``limit`` live entries with their size and time left, and
        whether there were more. Read-only; for the Overseer's Cache view."""
        if self._redis is not None:
            return await self._redis_entries(limit)
        assert self._store is not None
        now = time.time()
        live = [(k, v, exp) for k, (v, exp) in self._store.items() if exp > now]
        return (
            [CacheEntry(k, _pickled_size(v), exp - now) for k, v, exp in live[:limit]],
            len(live) > limit,
        )

    async def _redis_entries(self, limit: int) -> tuple[list[CacheEntry], bool]:
        keys: list[bytes] = []
        async for key in self._redis.scan_iter(count=500):
            if len(keys) == limit:
                return await self._sized(keys), True
            keys.append(key)
        return await self._sized(keys), False

    async def _sized(self, keys: list[bytes]) -> list[CacheEntry]:
        """Size and time left for each key, a pipeline per 500 keys."""
        found: list[CacheEntry] = []
        for start in range(0, len(keys), 500):
            batch = keys[start : start + 500]
            pipe = self._redis.pipeline(transaction=False)
            for key in batch:
                pipe.memory_usage(key)
                pipe.ttl(key)
            replies = await pipe.execute()
            for i, key in enumerate(batch):
                size, ttl = replies[2 * i], replies[2 * i + 1]
                if size is not None and ttl is not None and ttl >= 0:
                    found.append(CacheEntry(key.decode(), int(size), float(ttl)))
        return found

    async def values_with_prefix(self, prefix: str) -> dict[str, Any]:
        """Every live value whose key starts with ``prefix``, by key: for
        records kept one per key rather than in a list two writers race
        to rewrite. Not counted as hits or misses (a listing, not a read)."""
        if self._redis is not None:
            keys = await self._keys(prefix)
            blobs = await self._redis.mget(keys) if keys else []
            return {
                key.decode(): pickle.loads(blob)
                for key, blob in zip(keys, blobs, strict=True)
                if blob is not None
            }
        return dict(self._live(prefix))

    async def append_many(
        self,
        points: dict[str, float],
        *,
        at: float,
        keep_seconds: int,
        index: str | None = None,
    ) -> None:
        """Add one point at ``at`` to each time series in ``points`` (key to
        value) and drop the ones older than ``keep_seconds`` before ``at``
        (``app.core.series`` writes these). Redis keeps a sorted set per
        series scored by time, listed in the set ``index`` names so a read
        finds them without scanning the keyspace, all in one round trip."""
        if self._redis is not None:
            pipe = self._redis.pipeline(transaction=False)
            for key, value in points.items():
                pipe.zadd(key, {f"{at}:{value}": at})
                pipe.zremrangebyscore(key, "-inf", at - keep_seconds)
                pipe.expire(key, keep_seconds)
            if index is not None and points:
                pipe.sadd(index, *points)
                pipe.expire(index, keep_seconds)
            await pipe.execute()
            return
        assert self._store is not None
        for key, value in points.items():
            kept, _ = self._store.get(key, ([], 0.0))
            # Points arrive in time order: drop the stale ones from the front.
            del kept[: bisect_right(kept, at - keep_seconds, key=itemgetter(0))]
            kept.append((at, value))
            self._store[key] = (kept, time.time() + keep_seconds)

    async def points_with_prefix(
        self,
        prefix: str,
        *,
        since: float,
        index: str | None = None,
        ending: tuple[str, ...] = (),
    ) -> dict[str, list[tuple[float, float]]]:
        """Every time series whose key starts with ``prefix`` (and, given
        ``ending``, ends with one of those), by key: its points from
        ``since`` on, oldest first. With ``index`` (the set ``append``
        listed them in) Redis reads that set, not the keyspace."""
        if self._redis is None:
            found = {
                key: points[bisect_left(points, since, key=itemgetter(0)) :]
                for key, points in self._live(prefix)
                if not ending or key.endswith(ending)
            }
            return {key: points for key, points in found.items() if points}
        keys = (
            sorted(
                k
                for k in await self._redis.smembers(index)
                if k.decode().startswith(prefix)
            )
            if index is not None
            else await self._keys(prefix)
        )
        if ending:
            keys = [key for key in keys if key.decode().endswith(ending)]
        pipe = self._redis.pipeline(transaction=False)
        for key in keys:
            pipe.zrangebyscore(key, since, "+inf")
        replies = await pipe.execute()
        gone = [key for key, members in zip(keys, replies, strict=True) if not members]
        if index is not None and gone:  # expired series still listed
            await self._redis.srem(index, *gone)
        return {
            key.decode(): [_point(member) for member in members]
            for key, members in zip(keys, replies, strict=True)
            if members
        }

    async def claim(self, key: str, ttl: int) -> bool:
        """Take ``key`` for ``ttl`` seconds if nobody holds it: one process
        of many does a periodic job each round."""
        if self._redis is not None:
            return bool(await self._redis.set(key, b"1", nx=True, ex=ttl))
        if await self._lookup(key) is not None:
            return False
        assert self._store is not None
        self._store[key] = (True, time.time() + ttl)
        return True

    async def _keys(self, prefix: str) -> list[bytes]:
        """Every Redis key starting with ``prefix``: SCAN with MATCH, O(n)
        over the keyspace but never blocking the server, unlike KEYS."""
        return [
            key async for key in self._redis.scan_iter(match=f"{prefix}*", count=500)
        ]

    def _live(self, prefix: str) -> list[tuple[str, Any]]:
        """The in-memory entries under ``prefix`` that have not expired."""
        assert self._store is not None
        now = time.time()
        return [
            (key, value)
            for key, (value, expires_at) in list(self._store.items())
            if key.startswith(prefix) and expires_at > now
        ]

    async def invalidate(self, key: str) -> None:
        """Remove a specific key."""
        if self._redis is not None:
            await self._redis.delete(key)
            return
        assert self._store is not None
        self._store.pop(key, None)

    async def invalidate_prefix(self, prefix: str) -> int:
        """Remove every key starting with ``prefix``. Returns count removed.

        Used by per-namespace nukes where the exact key set is
        unbounded. Redis path uses SCAN with MATCH (O(n) over the
        keyspace but non-blocking, unlike KEYS), batched into a single
        DEL per page.
        """
        if self._redis is not None:
            keys = await self._keys(prefix)
            total = 0
            for start in range(0, len(keys), 500):  # one DEL per page
                total += await self._redis.delete(*keys[start : start + 500])
            return int(total)
        assert self._store is not None
        keys = [k for k in self._store if k.startswith(prefix)]
        for k in keys:
            self._store.pop(k, None)
        return len(keys)

    async def clear(self) -> None:
        """Remove all cached entries in this cache's namespace.

        Redis path: FLUSHDB on the cache's logical DB (``CACHE_REDIS_DB``).
        Safe because the cache lives on its own DB — arq's queue is on
        a different DB and isn't affected.
        """
        if self._redis is not None:
            await self._redis.flushdb()
            return
        assert self._store is not None
        self._store.clear()

    async def aclose(self) -> None:
        """Release the Redis connection pool.

        Long-lived processes (webserver, scheduler) never call this —
        the singleton lives for the lifetime of the process. Short-
        lived processes (CLI commands) should call it before the
        event loop tears down, otherwise the redis client's
        ``__del__`` fires after the loop is closed and emits a noisy
        ``RuntimeError: Event loop is closed`` traceback at GC time.
        The op already succeeded; the traceback is cosmetic. Calling
        ``aclose()`` cleanly suppresses it.

        No-op for the dict backend.
        """
        if self._redis is not None:
            await self._redis.aclose()


def _point(member: bytes) -> tuple[float, float]:
    """A time-series member as stored: ``b"<at>:<value>"``."""
    at, value = member.decode().split(":")
    return float(at), float(value)


def _pickled_size(value: Any) -> int:
    """What a value would take as stored; 0 if it cannot be pickled (the
    dict backend holds objects Redis could never have taken)."""
    try:
        return len(pickle.dumps(value))
    except (pickle.PicklingError, TypeError, AttributeError):
        return 0


def _build_singleton() -> CacheService:
    """Build the module-level singleton.

    Imports settings lazily inside the function so circular-import
    edge cases (settings → other code → cache → settings) don't trip
    at module load time.

    ``redis_url_effective`` only exists on stacks that opted into the
    Redis component. When absent, fall back to the dict backend —
    same shape as a test environment. No-Redis projects don't share
    cache state across processes, which is fine for single-process
    deployments.
    """
    from app.core.config import settings

    redis_url = getattr(settings, "redis_url_effective", None)
    redis_db = getattr(settings, "CACHE_REDIS_DB", 1)
    return CacheService(redis_url=redis_url, redis_db=redis_db)


cache = _build_singleton()


def get_cache() -> CacheService:
    """Dependency provider for CacheService."""
    return cache
