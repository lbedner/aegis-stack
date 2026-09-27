"""Per-source request-volume monitor — Overseer's "who's hammering you" view.

Sibling of the in-memory performance metrics service, but keyed on the
*source* (client IP) rather than the route: it counts requests per IP so an
operator can see at a glance when one address is driving a disproportionate
share of traffic, and the read path flags that source as "dominant."

Two backends, chosen the way ``CacheService`` picks one:

* **Redis** when a URL is configured (the Redis component is included) -
  shared across the webserver / scheduler / worker processes and surviving a
  restart for the bucket's TTL.
* **in-memory** otherwise - per-process and lost on restart. That's fine: the
  live panel still works because requests are *recorded* and *read back* in
  the same (backend) process. Cross-process auto-detection is the only thing
  that needs Redis, and that's a separate, optional tier.

Counts bucket by epoch hour so they age out on their own; only the heaviest
sources matter, so both backends keep just the top slice. Everything is
best-effort and fails OPEN - monitoring must never break a request or a panel.

Auto-discovered by ``backend_hooks`` because the file lives in
``app/components/backend/middleware/`` and exposes ``register_middleware``.
"""

from __future__ import annotations

import asyncio
from collections import Counter
import time
from typing import Any

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.components.backend.security.rate_limit import get_client_ip
from app.core.config import settings
from app.core.log import logger
from app.services.system.redis_keys import KeyFamily

_BUCKET_SECONDS = 3600
# Keep ~24h of hourly buckets; older ones are pruned (memory) or TTL'd (Redis).
_RETAIN_BUCKETS = 24
# Bound per-bucket cardinality so an IP-cycling flood can't grow memory / keys
# without limit - we only ever read the top.
_MAX_SOURCES_PER_BUCKET = 2000
# Per-bucket read cap when merging the windowed ranking (Redis path); a heavy
# source is top-of-bucket, so the deep tail can't change the top-N.
_READ_TOP = 200

# What this monitor keeps in Redis, for the keyspace map (``redis_keys``).
REDIS_KEYS = (
    KeyFamily(
        "traffic:sources:*",
        "zset",
        "Traffic sources",
        "Requests per client IP, one sorted set per hour, kept a day",
        "Backend traffic monitor",
        db="CACHE_REDIS_DB",
        columns=("Source IP", "Requests"),
    ),
    KeyFamily(
        "traffic:total:*",
        "string",
        "Traffic totals",
        "Every request counted per hour, the denominator for source shares",
        "Backend traffic monitor",
        db="CACHE_REDIS_DB",
        columns=("Hour", "Requests"),
    ),
)


class TrafficMonitor:
    """Per-source-IP request counts with a Redis-or-in-memory backend.

    Singleton ``traffic_monitor`` below; imported directly by the middleware
    (writes) and the traffic API (reads). Construct directly with
    ``redis_url=None`` for a self-contained in-memory instance (tests).
    """

    def __init__(self, *, redis_url: str | None = None, redis_db: int = 1) -> None:
        self._redis: Any = None
        self._buckets: dict[int, Counter[str]] | None = None
        self._totals: dict[int, int] | None = None
        if redis_url:
            # Lazy import so the in-memory path carries no redis dependency
            # (matches CacheService; no-Redis projects never import it).
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                redis_url,
                db=redis_db,
                decode_responses=True,
                socket_timeout=2,
                socket_connect_timeout=2,
            )
        else:
            self._buckets = {}
            self._totals = {}

    @property
    def backend(self) -> str:
        return "redis" if self._redis is not None else "memory"

    def _bucket(self, now: float | None = None) -> int:
        return int((now if now is not None else time.time()) // _BUCKET_SECONDS)

    async def record(self, client_ip: str | None) -> None:
        """Tally one request against its source IP. Best-effort, fails OPEN."""
        if not client_ip:
            return
        bucket = self._bucket()
        try:
            if self._redis is not None:
                ttl = _BUCKET_SECONDS * (_RETAIN_BUCKETS + 1)
                src_key = f"traffic:sources:{bucket}"
                total_key = f"traffic:total:{bucket}"
                await self._redis.zincrby(src_key, 1, client_ip)
                await self._redis.expire(src_key, ttl)
                # Trim the low-score tail; no-op until the set outgrows the cap.
                await self._redis.zremrangebyrank(
                    src_key, 0, -(_MAX_SOURCES_PER_BUCKET + 1)
                )
                # Exact denominator for share math (the trim drops the tail).
                await self._redis.incr(total_key)
                await self._redis.expire(total_key, ttl)
            else:
                assert self._buckets is not None and self._totals is not None
                self._buckets.setdefault(bucket, Counter())[client_ip] += 1
                self._totals[bucket] = self._totals.get(bucket, 0) + 1
                self._prune_memory(bucket)
        except Exception as e:
            logger.debug(f"TrafficMonitor.record soft-failed: {e}")

    def _prune_memory(self, current_bucket: int) -> None:
        assert self._buckets is not None and self._totals is not None
        cutoff = current_bucket - _RETAIN_BUCKETS
        for b in [b for b in self._buckets if b <= cutoff]:
            del self._buckets[b]
            self._totals.pop(b, None)
        counter = self._buckets.get(current_bucket)
        if counter is not None and len(counter) > _MAX_SOURCES_PER_BUCKET:
            # Keep the heaviest; the total counter retains the true denominator.
            self._buckets[current_bucket] = Counter(
                dict(counter.most_common(_MAX_SOURCES_PER_BUCKET))
            )

    async def snapshot(
        self,
        *,
        window_hours: int,
        limit: int,
        dominance_share: float,
        dominance_floor: int,
    ) -> dict[str, Any]:
        """Top sources over the trailing window + a read-time dominance flag.

        Returns ``{backend, window_hours, total_requests, sources, dominant}``
        where ``sources`` is ``[{ip, requests, share}]`` (heaviest first) and
        ``dominant`` is the lead source when it clears both thresholds, else
        ``None``. Fails OPEN to an empty shape.
        """
        now = time.time()
        buckets = [
            self._bucket(now - h * _BUCKET_SECONDS) for h in range(max(1, window_hours))
        ]
        vol: Counter[str] = Counter()
        total = 0
        try:
            if self._redis is not None:
                for b in buckets:
                    rows = await self._redis.zrevrange(
                        f"traffic:sources:{b}", 0, _READ_TOP - 1, withscores=True
                    )
                    for ip, score in rows:
                        vol[ip] += int(score)
                    t = await self._redis.get(f"traffic:total:{b}")
                    total += int(t) if t else 0
            else:
                assert self._buckets is not None and self._totals is not None
                for b in buckets:
                    counter = self._buckets.get(b)
                    if counter:
                        vol.update(counter)
                    total += self._totals.get(b, 0)
        except Exception as e:
            logger.debug(f"TrafficMonitor.snapshot soft-failed: {e}")
            return self._empty(window_hours)

        total = total or sum(vol.values())
        denom = total or 1
        sources = [
            {"ip": ip, "requests": count, "share": round(count / denom, 4)}
            for ip, count in vol.most_common(limit)
        ]
        dominant = None
        if sources:
            lead = sources[0]
            if lead["share"] >= dominance_share and lead["requests"] >= dominance_floor:
                dominant = lead
        return {
            "backend": self.backend,
            "window_hours": window_hours,
            "total_requests": int(total),
            "sources": sources,
            "dominant": dominant,
        }

    def _empty(self, window_hours: int) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "window_hours": window_hours,
            "total_requests": 0,
            "sources": [],
            "dominant": None,
        }

    def reset(self) -> None:
        """Drop all in-memory state. Test-only (no-op on the Redis backend)."""
        if self._buckets is not None:
            self._buckets.clear()
        if self._totals is not None:
            self._totals.clear()


def _build_monitor() -> TrafficMonitor:
    """Build the module-level singleton, mirroring the cache singleton.

    ``redis_url_effective`` only exists on stacks that opted into the Redis
    component; absent it, fall back to the in-memory backend (per-process,
    same tradeoff as the dict cache).
    """
    redis_url = getattr(settings, "redis_url_effective", None)
    redis_db = getattr(settings, "CACHE_REDIS_DB", 1)
    return TrafficMonitor(redis_url=redis_url, redis_db=redis_db)


# Singleton - imported directly by the middleware and the traffic API.
traffic_monitor = _build_monitor()

# Hold references to in-flight record tasks so they aren't garbage-collected
# mid-await (asyncio only keeps weak refs to tasks). Discarded on completion.
_record_tasks: set[asyncio.Task[None]] = set()


class TrafficMiddleware(BaseHTTPMiddleware):
    """Records each request's source IP into ``traffic_monitor``.

    Recording is fire-and-forget: the perf-metrics middleware can record
    synchronously because it's pure in-memory, but this one may touch Redis,
    so it must never add I/O latency to the response. The task is tracked
    (see ``_record_tasks``) and failures are swallowed inside ``record``.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        try:
            return await call_next(request)
        finally:
            # In ``finally`` so failed requests (scanners, 404s, 500s) count
            # too - exactly the traffic you want to see when probed.
            if settings.TRAFFIC_MONITOR_ENABLED:
                try:
                    task = asyncio.create_task(
                        traffic_monitor.record(get_client_ip(request))
                    )
                    _record_tasks.add(task)
                    task.add_done_callback(_record_tasks.discard)
                except Exception as e:
                    logger.debug(f"TrafficMiddleware: schedule failed: {e}")


def register_middleware(app: FastAPI) -> None:
    """Install the traffic-monitor middleware (auto-discovered by hooks)."""
    app.add_middleware(TrafficMiddleware)
    logger.info("Traffic monitor middleware registered")
