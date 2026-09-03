"""
Dramatiq task enqueueing utilities.

This module provides task enqueueing for Dramatiq-based workers.
Dramatiq's actor.send() is a sync Redis LPUSH. We wrap it with
asyncio.to_thread() to avoid blocking the FastAPI event loop.
"""

import asyncio
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

# Lazy-initialized Redis client for enqueue-side events


def get_task(task_name: str, queue_type: str | None = None) -> Any:
    """
    Get a registered task by name from the appropriate queue.

    Args:
        task_name: Name of the task function.
        queue_type: Queue type to look in. Defaults to configured default.

    Returns:
        The Dramatiq actor callable.

    Raises:
        ValueError: If the queue or the task is not found.
    """
    if queue_type is None:
        queue_type = get_default_queue()

    tasks = queue_tasks(queue_type)
    if not tasks:
        raise ValueError(f"Unknown queue type: {queue_type}")


    if task_name not in tasks:
        raise ValueError(f"Task '{task_name}' not found in {queue_type} queue")

    return tasks[task_name]


def get_broker(queue_type: str | None = None) -> Any:
    """
    Get the Dramatiq broker.

    Args:
        queue_type: Queue type (unused for Dramatiq — single global broker).

    Returns:
        The global Dramatiq broker instance.
    """
    import dramatiq

    return dramatiq.get_broker()


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
        Dramatiq Message for tracking.
    """
    if queue_type is None:
        queue_type = get_default_queue()

    if not is_valid_queue(queue_type):
        available = get_available_queues()
        raise ValueError(f"Invalid queue type '{queue_type}'. Available: {available}")

    task = get_task(task_name, queue_type)

    logger.info(f"Enqueueing task: {task_name} to {queue_type} queue")

    # Dramatiq's send() is sync (Redis LPUSH) — wrap to avoid blocking
    if delay_seconds:
        msg = await asyncio.to_thread(
            task.send_with_options,
            args=args,
            kwargs=kwargs,
            delay=delay_seconds * 1000,  # Dramatiq uses milliseconds
        )
    else:
        msg = await asyncio.to_thread(task.send, *args, **kwargs)

    logger.debug(f"Task enqueued with ID: {msg.message_id}")

    # Publish enqueue event for real-time dashboard updates
    try:
        redis_client = await events_redis()
        await publish_event(
            redis_client,
            "job.enqueued",
            queue_type or get_default_queue(),
            {"job_id": msg.message_id, "task": task_name},
        )
        # Record task enqueued in history
        from app.components.worker.task_history import record_task_enqueued

        await record_task_enqueued(
            redis_client,
            msg.message_id,
            task_name,
            queue_type or get_default_queue(),
            ttl_seconds=settings.TASK_HISTORY_TTL_SECONDS,
        )
    except Exception as e:
        logger.debug(f"Failed to publish enqueue event: {e}")

    return msg


async def get_task_result(
    task_id: str,
    queue_name: str = "system",
    actor_name: str = "",
    timeout: float = 30.0,
) -> Any:
    """
    Get the result of a completed task.

    Args:
        task_id: The task ID to look up.
        queue_name: Queue the task was sent to.
        actor_name: Actor name of the task (required for correct key lookup).
        timeout: Max seconds to wait for result.

    Returns:
        The task result if available.

    Raises:
        TimeoutError: If task doesn't complete within timeout.
    """
    import dramatiq

    backend = None
    for middleware in dramatiq.get_broker().middleware:
        if isinstance(middleware, dramatiq.results.Results):
            backend = middleware.backend
            break

    if backend is None:
        raise RuntimeError("No result backend configured")

    result = await asyncio.to_thread(
        backend.get_result,
        dramatiq.Message(
            queue_name=queue_name,
            actor_name=actor_name,
            args=(),
            kwargs={},
            options={},
            message_id=task_id,
        ),
        block=True,
        timeout=int(timeout * 1000),
    )
    return result


def clear_broker_cache() -> None:
    """Clear broker cache. No-op for Dramatiq (single global broker)."""
    logger.debug("Broker cache cleared (no-op for Dramatiq)")


async def shutdown_brokers() -> None:
    """
    Shut down the Dramatiq broker to prevent connection leaks.

    Call this before exiting CLI commands to ensure Redis connections
    are properly closed and avoid 'Event loop is closed' errors.
    """
    import dramatiq

    try:
        broker = dramatiq.get_broker()
        await asyncio.to_thread(broker.close)
        logger.debug("Shut down Dramatiq broker")
    except Exception as e:
        logger.debug(f"Error shutting down Dramatiq broker: {e}")

    await close_events_redis()
