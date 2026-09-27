"""
TaskIQ middleware for publishing worker events to Redis Streams.

Publishes job lifecycle events (started, completed, failed) from the worker
process. Enqueue-side events (job.enqueued) are handled separately in
pools_taskiq.py since middleware startup/shutdown run in the worker process,
not the client process.
"""

import asyncio
import sys
from typing import Any

import redis.asyncio as aioredis
from taskiq import TaskiqMessage, TaskiqMiddleware, TaskiqResult

from app.components.worker import runtime
from app.components.worker.events import publish_event
from app.components.worker.heartbeat import mark_busy, mark_idle, worker_id
from app.core.config import settings
from app.core.log import logger


def _short_name(task_name: str) -> str:
    """``module.path:func`` -> ``func``, the name enqueue records use."""
    return task_name.rsplit(":", 1)[-1]


def _short_name(task_name: str) -> str:
    """``module.path:func`` -> ``func``, the name enqueue records use."""
    return task_name.rsplit(":", 1)[-1]


class EventPublishMiddleware(TaskiqMiddleware):
    """Publishes worker lifecycle events to a Redis Stream."""

    _redis: aioredis.Redis | None = None
    _queue_name: str = "unknown"
    _reporting: asyncio.Task[None] | None = None

    def set_queue_name(self, queue_name: str) -> "EventPublishMiddleware":
        """Set the queue name for this middleware instance."""
        self._queue_name = queue_name
        return self

    async def startup(self) -> None:
        """Initialize the middleware on worker boot.

        Creates an async Redis connection and publishes a worker.started
        event to the Redis Stream. Called once when the TaskIQ worker
        process starts, before any tasks are consumed.
        """
        try:
            redis_url = (
                settings.redis_url_effective
                if hasattr(settings, "redis_url_effective")
                else settings.REDIS_URL
            )
            self._redis = aioredis.from_url(redis_url)
            await publish_event(self._redis, "worker.started", self._queue_name)
            launched = runtime.launch_settings("taskiq", sys.argv)
            self._reporting = runtime.start_reporting(
                self._redis,
                runtime.report(
                    worker=worker_id(),
                    queue=self._queue_name,
                    engine="taskiq",
                    version=runtime.engine_version("taskiq"),
                    **launched,
                ),
            )
        except Exception as e:
            logger.debug(f"Failed to initialize event publishing: {e}")

    async def shutdown(self) -> None:
        """Gracefully shut down the middleware.

        Publishes a worker.stopped event to the Redis Stream and closes
        the Redis connection. Called once when the TaskIQ worker process
        is shutting down, after all in-flight tasks have completed.
        """
        if self._redis:
            await runtime.stop_reporting(self._redis, self._reporting, worker_id())
            self._reporting = None
            await publish_event(self._redis, "worker.stopped", self._queue_name)
            await self._redis.aclose()
            self._redis = None

    async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """Run before each task executes.

        Publishes a job.started event to the Redis Stream and records
        the task as started in the task history. Fires after the message
        is acknowledged from the stream but before the task function runs.
        """
        if self._redis:
            await mark_busy(self._redis)
            await publish_event(
                self._redis,
                "job.started",
                self._queue_name,
                {"job_id": message.task_id, "task": message.task_name},
            )
            # Record task started in history
            from app.components.worker.task_history import record_task_started

            await record_task_started(
                self._redis,
                message.task_id,
                task_name=_short_name(message.task_name),
                queue_name=self._queue_name,
            )
        return message

    async def post_execute(
        self, message: TaskiqMessage, result: TaskiqResult[Any]
    ) -> None:
        """Run after each task completes or fails.

        Publishes a job.completed or job.failed event to the Redis Stream
        and records the final status in the task history. Fires after the
        task function returns (or raises), with the result available for
        inspection.
        """
        if self._redis:
            event_type = "job.failed" if result.is_err else "job.completed"
            await publish_event(
                self._redis,
                event_type,
                self._queue_name,
                {"job_id": message.task_id, "task": message.task_name},
            )
            # Record task finished in history
            from app.components.worker.task_history import record_task_finished

            error_msg = str(result.error) if result.is_err and result.error else None
            await record_task_finished(
                self._redis,
                message.task_id,
                success=not result.is_err,
                error=error_msg,
                task_name=_short_name(message.task_name),
                queue_name=self._queue_name,
            )
            await mark_idle(self._redis)
