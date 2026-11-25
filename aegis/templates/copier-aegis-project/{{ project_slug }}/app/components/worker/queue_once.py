"""A task queued once while it may still be waiting: work over many items
queues one task each (``task.fan-out``), and a sweep that finds an item
again before its task ran must not queue it twice."""

from typing import Any

from app.core.cache import get_cache


async def enqueue_once(
    key: str, ttl: int, task_name: str, queue: str, *args: Any
) -> bool:
    """Queue ``task_name`` on ``queue`` unless ``key`` is claimed; claimed
    for ``ttl`` seconds, after which a task that never ran is queued anew.
    Whether it was queued."""
    if not await get_cache().claim(key, ttl=ttl):
        return False
    from app.components.worker import pools

    await pools.enqueue_task(task_name, queue, *args)
    return True
