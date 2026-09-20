"""Writing a task's lifecycle down as it happens.

Each verb has an async form for the worker and a sync twin for the
call sites that have no loop to await on.
"""

from datetime import UTC, datetime
from typing import Any

from app.components.worker.task_history.shared import (
    _QUEUE_INDEX_PREFIX,
    _TASK_KEY_PREFIX,
    _enrich_mapping,
)
from app.core.log import logger


async def record_task_enqueued(
    redis: Any,
    job_id: str,
    task_name: str,
    queue_name: str,
    ttl_seconds: int = 86400,
) -> None:
    """Record a task being enqueued.

    Creates a Hash with initial metadata and adds the job to the
    per-queue sorted set.
    """
    now = datetime.now(UTC).isoformat()
    key = f"{_TASK_KEY_PREFIX}{job_id}"
    try:
        mapping: dict[str, str] = {
            "job_id": job_id,
            "queue": queue_name,
            "status": "enqueued",
            "enqueued_at": now,
        }
        _enrich_mapping(mapping, task_name)
        await redis.hset(key, mapping=mapping)
        await redis.expire(key, ttl_seconds)
        await redis.zadd(
            f"{_QUEUE_INDEX_PREFIX}{queue_name}",
            {job_id: datetime.now(UTC).timestamp()},
        )
    except Exception as e:
        logger.debug(f"Failed to record task enqueued: {e}")


async def record_task_started(
    redis: Any,
    job_id: str,
    task_name: str | None = None,
    queue_name: str | None = None,
    ttl_seconds: int = 86400,
) -> None:
    """Mark a task as started. Creates the record if it doesn't exist yet."""
    key = f"{_TASK_KEY_PREFIX}{job_id}"
    now = datetime.now(UTC)
    try:
        exists = await redis.exists(key)
        if not exists:
            # Create record on-the-fly (task was enqueued without recording)
            mapping: dict[str, str] = {
                "job_id": job_id,
                "status": "running",
                "started_at": now.isoformat(),
                "enqueued_at": now.isoformat(),
            }
            _enrich_mapping(mapping, task_name)
            if queue_name:
                mapping["queue"] = queue_name
            await redis.hset(key, mapping=mapping)
            await redis.expire(key, ttl_seconds)
            if queue_name:
                await redis.zadd(
                    f"{_QUEUE_INDEX_PREFIX}{queue_name}",
                    {job_id: now.timestamp()},
                )
        else:
            mapping = {
                "status": "running",
                "started_at": now.isoformat(),
            }
            _enrich_mapping(mapping, task_name)
            if queue_name:
                mapping["queue"] = queue_name
            await redis.hset(key, mapping=mapping)
    except Exception as e:
        logger.debug(f"Failed to record task started: {e}")


async def record_task_finished(
    redis: Any,
    job_id: str,
    success: bool,
    error: str | None = None,
    task_name: str | None = None,
    queue_name: str | None = None,
    ttl_seconds: int = 86400,
) -> None:
    """Mark a task as finished (success or failure). Creates record if missing."""
    key = f"{_TASK_KEY_PREFIX}{job_id}"
    try:
        now = datetime.now(UTC)
        exists = await redis.exists(key)
        if not exists:
            # Create record on-the-fly for tasks that bypassed enqueue recording
            mapping: dict[str, str] = {
                "job_id": job_id,
                "status": "completed" if success else "failed",
                "finished_at": now.isoformat(),
                "enqueued_at": now.isoformat(),
            }
            _enrich_mapping(mapping, task_name)
            if queue_name:
                mapping["queue"] = queue_name
            if error:
                mapping["error"] = str(error)[:2000]
            await redis.hset(key, mapping=mapping)
            await redis.expire(key, ttl_seconds)
            if queue_name:
                await redis.zadd(
                    f"{_QUEUE_INDEX_PREFIX}{queue_name}",
                    {job_id: now.timestamp()},
                )
            return

        mapping = {
            "status": "completed" if success else "failed",
            "finished_at": now.isoformat(),
        }
        _enrich_mapping(mapping, task_name)
        # Compute duration if started_at exists
        started_raw = await redis.hget(key, "started_at")
        if started_raw:
            started_str = (
                started_raw if isinstance(started_raw, str) else started_raw.decode()
            )
            started = datetime.fromisoformat(started_str)
            duration_ms = (now - started).total_seconds() * 1000
            mapping["duration_ms"] = f"{duration_ms:.1f}"
        if error:
            mapping["error"] = str(error)[:2000]
        await redis.hset(key, mapping=mapping)
    except Exception as e:
        logger.debug(f"Failed to record task finished: {e}")


def record_task_enqueued_sync(
    redis: Any,
    job_id: str,
    task_name: str,
    queue_name: str,
    ttl_seconds: int = 86400,
) -> None:
    """Sync variant of record_task_enqueued for Dramatiq."""
    now = datetime.now(UTC).isoformat()
    key = f"{_TASK_KEY_PREFIX}{job_id}"
    try:
        redis.hset(
            key,
            mapping={
                "job_id": job_id,
                "name": task_name,
                "queue": queue_name,
                "status": "enqueued",
                "enqueued_at": now,
            },
        )
        redis.expire(key, ttl_seconds)
        redis.zadd(
            f"{_QUEUE_INDEX_PREFIX}{queue_name}",
            {job_id: datetime.now(UTC).timestamp()},
        )
    except Exception as e:
        logger.debug(f"Failed to record task enqueued (sync): {e}")


def record_task_started_sync(
    redis: Any,
    job_id: str,
    task_name: str | None = None,
    queue_name: str | None = None,
    ttl_seconds: int = 86400,
) -> None:
    """Sync variant of record_task_started for Dramatiq.

    Creates the record on-the-fly if it doesn't exist yet (e.g. sub-tasks
    dispatched via ``actor.send()`` that bypassed ``record_task_enqueued``).
    """
    key = f"{_TASK_KEY_PREFIX}{job_id}"
    now = datetime.now(UTC)
    try:
        if not redis.exists(key):
            mapping: dict[str, str] = {
                "job_id": job_id,
                "status": "running",
                "started_at": now.isoformat(),
                "enqueued_at": now.isoformat(),
            }
            _enrich_mapping(mapping, task_name)
            if queue_name:
                mapping["queue"] = queue_name
            redis.hset(key, mapping=mapping)
            redis.expire(key, ttl_seconds)
            if queue_name:
                redis.zadd(
                    f"{_QUEUE_INDEX_PREFIX}{queue_name}",
                    {job_id: now.timestamp()},
                )
            return
        mapping = {
            "status": "running",
            "started_at": now.isoformat(),
        }
        _enrich_mapping(mapping, task_name)
        if queue_name:
            mapping["queue"] = queue_name
        redis.hset(key, mapping=mapping)
    except Exception as e:
        logger.debug(f"Failed to record task started (sync): {e}")


def record_task_finished_sync(
    redis: Any,
    job_id: str,
    success: bool,
    error: str | None = None,
    task_name: str | None = None,
    queue_name: str | None = None,
    ttl_seconds: int = 86400,
) -> None:
    """Sync variant of record_task_finished for Dramatiq.

    Creates the record on-the-fly if it doesn't exist yet.
    """
    key = f"{_TASK_KEY_PREFIX}{job_id}"
    try:
        now = datetime.now(UTC)
        if not redis.exists(key):
            mapping: dict[str, str] = {
                "job_id": job_id,
                "status": "completed" if success else "failed",
                "finished_at": now.isoformat(),
                "enqueued_at": now.isoformat(),
            }
            _enrich_mapping(mapping, task_name)
            if queue_name:
                mapping["queue"] = queue_name
            if error:
                mapping["error"] = str(error)[:2000]
            redis.hset(key, mapping=mapping)
            redis.expire(key, ttl_seconds)
            if queue_name:
                redis.zadd(
                    f"{_QUEUE_INDEX_PREFIX}{queue_name}",
                    {job_id: now.timestamp()},
                )
            return
        mapping = {
            "status": "completed" if success else "failed",
            "finished_at": now.isoformat(),
        }
        _enrich_mapping(mapping, task_name)
        started_raw = redis.hget(key, "started_at")
        if started_raw:
            started_str = (
                started_raw if isinstance(started_raw, str) else started_raw.decode()
            )
            started = datetime.fromisoformat(started_str)
            duration_ms = (now - started).total_seconds() * 1000
            mapping["duration_ms"] = f"{duration_ms:.1f}"
        if error:
            mapping["error"] = str(error)[:2000]
        redis.hset(key, mapping=mapping)
    except Exception as e:
        logger.debug(f"Failed to record task finished (sync): {e}")
