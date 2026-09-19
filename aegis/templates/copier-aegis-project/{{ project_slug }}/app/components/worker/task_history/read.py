"""Reading the history back: one task, a queue, or the totals."""

from typing import Any

from app.components.worker.task_history.prune import _cleanup_expired_members
from app.components.worker.task_history.shared import (
    _QUEUE_INDEX_PREFIX,
    _TASK_KEY_PREFIX,
)
from app.core.log import logger


async def get_task_record(redis: Any, job_id: str) -> dict[str, str] | None:
    """Retrieve a single task record by job ID."""
    key = f"{_TASK_KEY_PREFIX}{job_id}"
    try:
        data = await redis.hgetall(key)
        if not data:
            return None
        # Decode bytes keys/values if needed
        return {
            (k if isinstance(k, str) else k.decode()): (
                v if isinstance(v, str) else v.decode()
            )
            for k, v in data.items()
        }
    except Exception as e:
        logger.debug(f"Failed to get task record: {e}")
        return None


async def _pipeline_get_records(redis: Any, job_ids: list[str]) -> list[dict[str, str]]:
    """Fetch multiple task records in a single Redis pipeline round trip."""
    if not job_ids:
        return []
    pipe = redis.pipeline(transaction=False)
    for jid in job_ids:
        pipe.hgetall(f"{_TASK_KEY_PREFIX}{jid}")
    results = await pipe.execute()
    tasks: list[dict[str, str]] = []
    for data in results:
        if not data:
            continue
        record = {
            (k if isinstance(k, str) else k.decode()): (
                v if isinstance(v, str) else v.decode()
            )
            for k, v in data.items()
        }
        tasks.append(record)
    return tasks


async def _pipeline_get_statuses(redis: Any, job_ids: list[str]) -> list[str | None]:
    """Fetch only the status field for multiple tasks in one pipeline."""
    if not job_ids:
        return []
    pipe = redis.pipeline(transaction=False)
    for jid in job_ids:
        pipe.hget(f"{_TASK_KEY_PREFIX}{jid}", "status")
    results = await pipe.execute()
    return [(r if isinstance(r, str) else r.decode()) if r else None for r in results]


async def get_queue_stats(
    redis: Any,
    queue_name: str,
    limit: int = 0,
) -> dict[str, int]:
    """Count tasks by status for a queue.

    Args:
        redis: Async Redis client.
        queue_name: Queue name to count stats for.
        limit: If > 0, only scan the most recent N tasks (faster for health checks).
               If 0, scan all tasks.

    Returns:
        Dict with keys: running, completed, failed, total.
    """
    index_key = f"{_QUEUE_INDEX_PREFIX}{queue_name}"
    try:
        if limit > 0:
            all_ids_raw = await redis.zrevrange(index_key, 0, limit - 1)
        else:
            all_ids_raw = await redis.zrange(index_key, 0, -1)
        if not all_ids_raw:
            return {"running": 0, "completed": 0, "failed": 0, "total": 0}

        all_ids = [j if isinstance(j, str) else j.decode() for j in all_ids_raw]
        statuses = await _pipeline_get_statuses(redis, all_ids)

        counts = {"running": 0, "completed": 0, "failed": 0, "total": len(all_ids)}
        for s in statuses:
            if s in counts:
                counts[s] += 1
        return counts
    except Exception as e:
        logger.debug(f"Failed to get queue stats: {e}")
        return {"running": 0, "completed": 0, "failed": 0, "total": 0}


async def list_tasks_by_queue(
    redis: Any,
    queue_name: str,
    offset: int = 0,
    limit: int = 50,
    order: str = "desc",
    status: str | None = None,
) -> tuple[list[dict[str, str]], int]:
    """List task records for a queue with pagination.

    Lazily removes expired members from the sorted set.
    Uses Redis pipelines to minimise round trips.
    When ``status`` is provided, records are post-filtered and the
    returned total reflects only matching records.

    Returns:
        Tuple of (task records, total count).
    """
    index_key = f"{_QUEUE_INDEX_PREFIX}{queue_name}"
    try:
        # Lazy cleanup: remove members whose hash has expired
        await _cleanup_expired_members(redis, index_key)

        if status:
            # Status filter: pipeline-fetch statuses, filter, then paginate
            if order == "desc":
                all_ids_raw = await redis.zrevrange(index_key, 0, -1)
            else:
                all_ids_raw = await redis.zrange(index_key, 0, -1)

            all_ids = [j if isinstance(j, str) else j.decode() for j in all_ids_raw]
            statuses = await _pipeline_get_statuses(redis, all_ids)
            matching_ids = [
                jid for jid, s in zip(all_ids, statuses, strict=False) if s == status
            ]
            total = len(matching_ids)
            page_ids = matching_ids[offset : offset + limit]
            tasks = await _pipeline_get_records(redis, page_ids)
        else:
            total = await redis.zcard(index_key)

            if order == "desc":
                job_ids_raw = await redis.zrevrange(
                    index_key, offset, offset + limit - 1
                )
            else:
                job_ids_raw = await redis.zrange(index_key, offset, offset + limit - 1)

            job_ids = [j if isinstance(j, str) else j.decode() for j in job_ids_raw]
            tasks = await _pipeline_get_records(redis, job_ids)
        return tasks, total
    except Exception as e:
        logger.debug(f"Failed to list tasks by queue: {e}")
        return [], 0
