"""
Worker heartbeat for rolling-deploy drain detection.

Each worker SETEXs ``worker:<host>:<pid>:busy`` for the duration of a
job and refreshes the TTL on a background task/thread so the key never
expires mid-execution. The ``aegis deploy --rolling`` command polls
``SCAN`` for ``worker:*:busy`` after setting the pause flag and proceeds
once empty (or aborts on timeout). Keeping the signal in Redis — rather
than in broker internals — means the same deploy-side drain check works
regardless of queue library (taskiq, dramatiq, arq).

TTL is intentionally short (so a worker that dies mid-job disappears
from the drain check well before the deploy's drain timeout) and
refreshed at ``TTL / 2`` while the job runs (so jobs longer than the
TTL never self-expire).

Best-effort: a Redis blip must never fail a job, so callers should not
propagate exceptions from these helpers.

The busy key is process-scoped (``worker:<host>:<pid>:busy``), but a
single process runs jobs concurrently (taskiq async tasks, dramatiq
threads). The helpers reference-count in-flight jobs so the key and its
refresh loop are torn down only when the *last* job on the process
finishes — otherwise the first job to complete would delete the key
while siblings are still running and let the drain check proceed early.

The key's value is that count, so Overseer can show each process's
running jobs (``with_busy``) on every backend: arq and taskiq call the
async helpers, dramatiq the sync ones. A job starting writes it; a job
ending does not (the next start, or the refresh, does), which keeps job
ends free of a Redis call.
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading

import redis as sync_redis
import redis.asyncio as aioredis

from app.core.log import logger
from app.core.key_family import KeyFamily

BUSY_KEY_PREFIX = "worker:"
BUSY_KEY_SUFFIX = ":busy"
DEFAULT_TTL_SECONDS = 30
# Set by ``aegis deploy --rolling`` while it drains: every backend stops
# taking jobs while it exists (taskiq's and dramatiq's brokers, arq's
# ``arq_hooks.follow_pause``), so the busy keys can clear.
PAUSE_KEY = "aegis:queue:paused"
PAUSE_POLL_SECONDS = 1.0

REDIS_KEYS = (
    KeyFamily(
        f"{BUSY_KEY_PREFIX}*{BUSY_KEY_SUFFIX}",
        "string",
        "Busy workers",
        "One per worker mid-job, refreshed while it runs; deploys drain on these",
        "Worker heartbeat",
        columns=("Worker", "Since"),
    ),
    KeyFamily(
        PAUSE_KEY,
        "string",
        "Queue pause",
        "Set during a rolling deploy so workers stop taking new jobs",
        "Worker heartbeat",
        columns=("Key", "Value"),
    ),
)

_worker_id: str | None = None
_refresh_task: asyncio.Task[None] | None = None
_busy_count: int = 0
_refresh_thread: threading.Thread | None = None
_refresh_stop: threading.Event | None = None
_busy_count_sync: int = 0
_busy_lock = threading.Lock()


def worker_id() -> str:
    """Return a stable identifier for this worker process."""
    global _worker_id
    if _worker_id is None:
        _worker_id = f"{socket.gethostname()}:{os.getpid()}"
    return _worker_id


def busy_key(wid: str | None = None) -> str:
    return f"{BUSY_KEY_PREFIX}{wid or worker_id()}{BUSY_KEY_SUFFIX}"


# ---------------------------------------------------------------------------
# Async variant (taskiq, arq)
# ---------------------------------------------------------------------------


async def _refresh_loop(
    redis: aioredis.Redis, ttl_seconds: int, interval: float
) -> None:
    key = busy_key()
    while True:
        await asyncio.sleep(interval)
        try:
            await redis.set(key, str(_busy_count), ex=ttl_seconds)
        except Exception as exc:
            logger.debug("heartbeat refresh failed: %s", exc)


async def mark_busy(
    redis: aioredis.Redis, ttl_seconds: int = DEFAULT_TTL_SECONDS
) -> None:
    """Mark this worker as actively executing a job.

    Sets the busy key with a short TTL and starts a background task
    that refreshes it at ``ttl_seconds / 2``. The TTL stays short so a
    crashed worker drops out of the drain check quickly; the refresh
    keeps long-running jobs from self-expiring.

    Reference-counted: concurrent jobs share one key and one refresh
    task, started only on the first in-flight job.
    """
    global _refresh_task, _busy_count
    _busy_count += 1
    try:
        await redis.set(busy_key(), str(_busy_count), ex=ttl_seconds)
    except Exception as exc:
        logger.debug("heartbeat mark_busy failed: %s", exc)
        _busy_count -= 1
        return

    if _refresh_task is None or _refresh_task.done():
        interval = max(1.0, ttl_seconds / 2)
        _refresh_task = asyncio.create_task(_refresh_loop(redis, ttl_seconds, interval))


async def mark_idle(redis: aioredis.Redis) -> None:
    """Mark this worker as idle (no job in flight).

    Decrements the in-flight count; only the last concurrent job to
    finish stops the refresh task and deletes the busy key.
    """
    global _refresh_task, _busy_count
    if _busy_count > 0:
        _busy_count -= 1
    if _busy_count > 0:
        return
    if _refresh_task is not None:
        _refresh_task.cancel()
        try:
            await _refresh_task
        except (asyncio.CancelledError, Exception):
            pass
        _refresh_task = None
    try:
        await redis.delete(busy_key())
    except Exception as exc:
        logger.debug("heartbeat mark_idle failed: %s", exc)


# ---------------------------------------------------------------------------
# Sync variant (dramatiq)
# ---------------------------------------------------------------------------


def _refresh_loop_sync(
    redis: sync_redis.Redis,
    ttl_seconds: int,
    interval: float,
    stop: threading.Event,
) -> None:
    key = busy_key()
    while not stop.wait(interval):
        try:
            redis.set(key, str(_busy_count_sync), ex=ttl_seconds)
        except Exception as exc:
            logger.debug("heartbeat refresh failed: %s", exc)


def mark_busy_sync(
    redis: sync_redis.Redis, ttl_seconds: int = DEFAULT_TTL_SECONDS
) -> None:
    """Sync variant of :func:`mark_busy` for dramatiq middleware.

    Reference-counted across dramatiq worker threads, which share one
    process (one busy key): the refresh thread starts only on the first
    in-flight job.
    """
    global _refresh_thread, _refresh_stop, _busy_count_sync
    with _busy_lock:
        _busy_count_sync += 1
        try:
            redis.set(busy_key(), str(_busy_count_sync), ex=ttl_seconds)
        except Exception as exc:
            logger.debug("heartbeat mark_busy_sync failed: %s", exc)
            _busy_count_sync -= 1
            return

        if _refresh_thread is None or not _refresh_thread.is_alive():
            _refresh_stop = threading.Event()
            interval = max(1.0, ttl_seconds / 2)
            _refresh_thread = threading.Thread(
                target=_refresh_loop_sync,
                args=(redis, ttl_seconds, interval, _refresh_stop),
                daemon=True,
            )
            _refresh_thread.start()


def mark_idle_sync(redis: sync_redis.Redis) -> None:
    """Sync variant of :func:`mark_idle` for dramatiq middleware.

    Only the last concurrent worker thread to finish stops the refresh
    thread and deletes the busy key.
    """
    global _refresh_thread, _refresh_stop, _busy_count_sync
    with _busy_lock:
        if _busy_count_sync > 0:
            _busy_count_sync -= 1
        if _busy_count_sync > 0:
            return
        if _refresh_stop is not None:
            _refresh_stop.set()
            _refresh_stop = None
        thread = _refresh_thread
        _refresh_thread = None
    # Join outside the lock so the refresh thread isn't blocked waiting
    # on a lock we're holding while we wait on it.
    if thread is not None:
        thread.join(timeout=2.0)
    try:
        redis.delete(busy_key())
    except Exception as exc:
        logger.debug("heartbeat mark_idle_sync failed: %s", exc)


async def with_busy(
    redis: aioredis.Redis, reports: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Each worker's runtime report with ``busy``: how many jobs its process
    is running now, read in one round trip (no key: none)."""
    pipe = redis.pipeline(transaction=False)
    for report in reports:
        pipe.get(busy_key(report.get("worker", "")))
    counts = await pipe.execute()
    return [
        report | {"busy": str(int(count or 0))}
        for report, count in zip(reports, counts, strict=True)
    ]
