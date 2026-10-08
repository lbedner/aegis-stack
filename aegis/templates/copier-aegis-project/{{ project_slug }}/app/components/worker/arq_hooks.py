"""The hooks every arq queue runs around its worker and its jobs.

arq has no middleware: each queue is its own worker process, configured by
its own ``WorkerSettings``, and arq reads the hooks from that class's own
``__dict__`` (``arq.worker.get_kwargs``), so an inherited hook never runs.
Each queue assigns these instead, built for its name:

    on_startup, on_shutdown, on_job_start, after_job_end = arq_hooks.for_queue(
        QueueName.SYSTEM, max_jobs
    )

TaskIQ and dramatiq do the same work once, in their event middleware. Only
arq stacks ship this module.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from arq.constants import result_key_prefix
from arq.jobs import deserialize_result
import redis.asyncio as aioredis

from app.components.worker import runtime
from app.components.worker.events import publish_event
from app.components.worker.heartbeat import (
    PAUSE_KEY,
    PAUSE_POLL_SECONDS,
    mark_busy,
    mark_idle,
    worker_id,
)
from app.components.worker.task_history import (
    record_task_finished,
    record_task_started,
    resolve_arq_task_name,
)
from app.core.boot import apply_saved_overrides
from app.core.config import settings
from app.core.log import logger

Hook = Callable[[dict[str, Any]], Awaitable[None]]


async def follow_pause(worker: Any, redis: aioredis.Redis) -> None:
    """Stop the worker taking jobs while a rolling deploy has the queues
    paused (``PAUSE_KEY``), and let it take them again after.

    taskiq's and dramatiq's brokers check the key before each read; arq
    has no broker to subclass, so this flips its ``allow_pick_jobs``. Only
    a pause this set is undone: arq's own graceful shutdown turns picking
    off too, and must stay off.
    """
    paused = False
    while True:
        try:
            wanted = bool(await redis.get(PAUSE_KEY))
        except Exception as e:  # a Redis blip must not stop the worker
            logger.debug(f"Could not read the queue pause: {e}")
            wanted = paused
        if wanted and not paused and worker.allow_pick_jobs:
            worker.allow_pick_jobs, paused = False, True
        elif paused and not wanted:
            worker.allow_pick_jobs, paused = True, False
        await asyncio.sleep(PAUSE_POLL_SECONDS)


def for_queue(queue: str, max_jobs: int) -> tuple[Hook, Hook, Hook, Hook]:
    """``on_startup``, ``on_shutdown``, ``on_job_start`` and ``after_job_end``
    for one queue; ``max_jobs`` is what its worker reports it runs with."""

    async def on_startup(ctx: dict[str, Any]) -> None:
        """Apply what the Overseer saved, then publish worker.started."""
        await apply_saved_overrides()
        try:
            redis_url = settings.redis_url_effective
            ctx["events_redis"] = aioredis.from_url(redis_url)
            ctx["worker_queue_name"] = queue
            await publish_event(ctx["events_redis"], "worker.started", queue)
            ctx["runtime_reporting"] = runtime.start_reporting(
                ctx["events_redis"],
                runtime.report(
                    worker=worker_id(),
                    queue=queue,
                    engine="arq",
                    version=runtime.engine_version("arq"),
                    processes=1,
                    concurrency=max_jobs,
                ),
            )
        except Exception as e:
            logger.debug(f"Failed to initialize event publishing: {e}")

    async def on_shutdown(ctx: dict[str, Any]) -> None:
        """Publish worker.stopped event on worker shutdown."""
        if "events_redis" in ctx:
            await runtime.stop_reporting(
                ctx["events_redis"], ctx.get("runtime_reporting"), worker_id()
            )
            await publish_event(ctx["events_redis"], "worker.stopped", queue)
            await ctx["events_redis"].aclose()

    async def on_job_start(ctx: dict[str, Any]) -> None:
        """Mark the process busy, publish job.started and record the task in
        its history."""
        if "events_redis" not in ctx:
            return
        redis = ctx["events_redis"]
        job_id = str(ctx.get("job_id", "unknown"))
        await mark_busy(redis)
        await publish_event(redis, "job.started", queue, {"job_id": job_id})
        task_name = await resolve_arq_task_name(redis, job_id)
        await record_task_started(redis, job_id, task_name=task_name, queue_name=queue)

    async def after_job_end(ctx: dict[str, Any]) -> None:
        """Publish job.completed or job.failed, record how it ended, and mark
        the process one job less busy."""
        if "events_redis" not in ctx:
            return
        redis = ctx["events_redis"]
        job_id = str(ctx.get("job_id", "unknown"))
        await mark_idle(redis)
        # arq's stored result says how it ended; without one, it succeeded.
        success, error, task_name = True, None, None
        try:
            if raw := await redis.get(result_key_prefix + job_id):
                result = deserialize_result(raw)
                success, task_name = result.success, result.function
                if not success and result.result:
                    error = str(result.result)
        except Exception as e:
            logger.debug(f"Could not read arq's result for job {job_id}: {e}")
        await publish_event(
            redis,
            "job.completed" if success else "job.failed",
            queue,
            {"job_id": job_id, "status": "success" if success else "failed"},
        )
        await record_task_finished(
            redis,
            job_id,
            success=success,
            error=error,
            task_name=task_name,
            queue_name=queue,
        )

    hooks = (on_startup, on_shutdown, on_job_start, after_job_end)
    for hook in hooks:
        # The Overseer names a hook by its qualname: the hook, not this factory.
        hook.__qualname__ = hook.__name__
    return hooks
