"""Letting history expire, by age or on request."""

from datetime import UTC, datetime
from typing import Any

from app.components.worker.task_history.shared import (
    _QUEUE_INDEX_PREFIX,
    _TASK_KEY_PREFIX,
)
from app.core.log import logger


async def cleanup_old_tasks(
    redis: Any,
    queue_name: str,
    max_age_seconds: int,
) -> int:
    """Remove tasks older than max_age_seconds from the sorted set.

    Hash keys auto-expire via TTL; this cleans up the sorted set index.

    Returns:
        Number of entries removed.
    """
    index_key = f"{_QUEUE_INDEX_PREFIX}{queue_name}"
    try:
        cutoff = datetime.now(UTC).timestamp() - max_age_seconds
        removed: int = await redis.zremrangebyscore(index_key, "-inf", cutoff)
        return removed
    except Exception as e:
        logger.debug(f"Failed to cleanup old tasks: {e}")
        return 0


async def clear_queue_history(redis: Any, queue_name: str) -> int:
    """Delete all task history for a queue.

    Removes hash keys and the sorted set index.

    Returns:
        Number of task records deleted.
    """
    index_key = f"{_QUEUE_INDEX_PREFIX}{queue_name}"
    try:
        job_ids = await redis.zrange(index_key, 0, -1)
        count = 0
        for jid in job_ids:
            jid_str = jid if isinstance(jid, str) else jid.decode()
            await redis.delete(f"{_TASK_KEY_PREFIX}{jid_str}")
            count += 1
        await redis.delete(index_key)
        return count
    except Exception as e:
        logger.debug(f"Failed to clear queue history: {e}")
        return 0


async def _cleanup_expired_members(redis: Any, index_key: str) -> None:
    """Remove sorted set members whose hash key has expired.

    Uses a pipeline to check existence in a single round trip.
    """
    try:
        members = await redis.zrange(index_key, 0, 99)
        if not members:
            return
        member_strs = [m if isinstance(m, str) else m.decode() for m in members]
        pipe = redis.pipeline(transaction=False)
        for m_str in member_strs:
            pipe.exists(f"{_TASK_KEY_PREFIX}{m_str}")
        results = await pipe.execute()
        expired = [
            m for m, exists in zip(member_strs, results, strict=False) if not exists
        ]
        if expired:
            await redis.zrem(index_key, *expired)
    except Exception:
        pass  # best-effort cleanup
