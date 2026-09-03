"""
TaskIQ task enqueueing utilities.

This module provides broker access and task enqueueing for TaskIQ-based workers.
Unlike arq which requires explicit connection pooling, TaskIQ brokers handle
their own connections internally.
"""

from typing import Any

from app.components.worker.events import (
    close_events_redis,
    events_redis,
    publish_event,
)
from app.components.worker.registry import queue_tasks
from app.core.config import (
    get_available_queues,
    get_default_queue,
    is_valid_queue,
    settings,
)
from app.core.log import logger

# Broker cache to avoid re-importing
_broker_cache: dict[str, Any] = {}

# Lazy-initialized Redis client for enqueue-side events


def get_broker(queue_type: str | None = None) -> Any:
    """
    Get the TaskIQ broker for a specific queue type.

    Args:
        queue_type: Queue type (system, load_test). Defaults to configured default.

    Returns:
        The TaskIQ broker instance for the queue.

    Raises:
        ValueError: If queue type is invalid.
    """
    if queue_type is None:
        queue_type = get_default_queue()

    if not is_valid_queue(queue_type):
        available = get_available_queues()
        raise ValueError(f"Invalid queue type '{queue_type}'. Available: {available}")

    if queue_type in _broker_cache:
        return _broker_cache[queue_type]

    # Dynamic import based on queue type
    if queue_type == "system":
        from app.components.worker.queues.system import broker

        _broker_cache[queue_type] = broker
    elif queue_type == "load_test":
        from app.components.worker.queues.load_test import broker

        _broker_cache[queue_type] = broker
    else:
        raise ValueError(f"Unknown queue type: {queue_type}")

    logger.debug(f"Loaded broker for queue: {queue_type}")
    return _broker_cache[queue_type]


def get_task(task_name: str, queue_type: str | None = None) -> Any:
    """
    Get a registered task by name from the appropriate queue.

    Args:
        task_name: Name of the task function.
        queue_type: Queue type to look in. Defaults to configured default.

    Returns:
        The TaskIQ task callable.

    Raises:
        ValueError: If the queue or the task is not found.
    """
    if queue_type is None:
        queue_type = get_default_queue()

    tasks = queue_tasks(queue_type)
    if not tasks:
        raise ValueError(f"Unknown queue type: {queue_type}")

    _broker_cache[queue_type] = get_broker(queue_type)

    if task_name not in tasks:
        raise ValueError(f"Task '{task_name}' not found in {queue_type} queue")

    return tasks[task_name]


async def enqueue_task(
    task_name: str,
    queue_type: str | None = None,
    *args: Any,
    delay_seconds: int | None = None,
    **kwargs: Any,
) -> Any:
    """
    Enqueue a task for background processing.

    Args:
        task_name: Name of the task to enqueue.
        queue_type: Target queue type. Defaults to configured default.
        *args: Positional arguments for the task.
        delay_seconds: Optional delay before task execution.
        **kwargs: Keyword arguments for the task.

    Returns:
        TaskIQ task handle (AsyncTaskiqTask) for tracking.
    """
    if queue_type is None:
        queue_type = get_default_queue()

    task = get_task(task_name, queue_type)

    logger.info(f"Enqueueing task: {task_name} to {queue_type} queue")

    # TaskIQ uses .kiq() to enqueue tasks
    if delay_seconds:
        # TaskIQ supports delayed execution via labels
        task_handle = await task.kiq(*args, **kwargs)
        # Note: TaskIQ delay is handled differently - via scheduler or labels
        # For now, log warning if delay requested
        logger.warning(
            f"Task delay ({delay_seconds}s) requested but TaskIQ delay "
            "requires taskiq-scheduler integration"
        )
    else:
        task_handle = await task.kiq(*args, **kwargs)

    logger.debug(f"Task enqueued with ID: {task_handle.task_id}")

    # Publish enqueue event for real-time dashboard updates
    try:
        redis_client = await events_redis()
        await publish_event(
            redis_client,
            "job.enqueued",
            queue_type or get_default_queue(),
            {"job_id": str(task_handle.task_id), "task": task_name},
        )
        # Record task enqueued in history
        from app.components.worker.task_history import record_task_enqueued

        await record_task_enqueued(
            redis_client,
            str(task_handle.task_id),
            task_name,
            queue_type or get_default_queue(),
            ttl_seconds=settings.TASK_HISTORY_TTL_SECONDS,
        )
    except Exception as e:
        logger.debug(f"Failed to publish enqueue event: {e}")

    return task_handle


async def get_task_result(task_id: str, timeout: float = 30.0) -> Any:
    """
    Get the result of a completed task.

    Args:
        task_id: The task ID to look up.
        timeout: Max seconds to wait for result.

    Returns:
        The task result if available.

    Raises:
        TimeoutError: If task doesn't complete within timeout.
    """
    # TaskIQ result retrieval requires the task handle or result backend
    # This is a simplified version - full implementation would use result backend
    from app.components.worker.queues.system import broker

    result_backend = broker.result_backend
    if result_backend is None:
        raise RuntimeError("No result backend configured")

    result = await result_backend.get_result(task_id)
    return result


def clear_broker_cache() -> None:
    """Clear the broker cache. Useful for testing."""
    _broker_cache.clear()
    logger.debug("Broker cache cleared")


async def shutdown_brokers() -> None:
    """
    Shut down all cached brokers to prevent connection leaks.

    Call this before exiting CLI commands to ensure Redis connections
    are properly closed and avoid 'Event loop is closed' errors.
    """
    for queue_type, broker in _broker_cache.items():
        try:
            await broker.shutdown()
            logger.debug(f"Shut down broker for queue: {queue_type}")
        except Exception as e:
            logger.debug(f"Error shutting down broker for {queue_type}: {e}")
    _broker_cache.clear()

    await close_events_redis()
