"""
Media worker queue configuration.

Handles image processing, file operations, and media transformations using native
arq patterns.
"""

from typing import Any

import redis.asyncio as aioredis
from app.components.worker import runtime
from app.components.worker.events import publish_event
from app.components.worker.heartbeat import worker_id
from app.core.config import settings
from app.core.log import logger
from app.core.queue_workers import concurrency_for
from arq.connections import RedisSettings
from arq.constants import result_key_prefix
from arq.jobs import deserialize_result

# Import media tasks (when available)
# from app.components.worker.tasks.media_tasks import (
#     image_resize,
#     video_encode,
#     file_convert,
# )


class WorkerSettings:
    """Media processing worker configuration."""

    # Human-readable description
    description = "Image and file processing"

    # Task functions for this queue
    functions: list[Any] = [
        # Media processing tasks will be added here
        # Example: image_resize, video_encode, file_convert
    ]

    # arq configuration with improved connection settings
    base_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    redis_settings = RedisSettings(
        host=base_settings.host,
        port=base_settings.port,
        database=base_settings.database,
        password=base_settings.password,
        conn_timeout=settings.REDIS_CONN_TIMEOUT,
        conn_retries=settings.REDIS_CONN_RETRIES,
        conn_retry_delay=settings.REDIS_CONN_RETRY_DELAY,
    )
    queue_name = "arq:queue:media"
    max_jobs = concurrency_for("media")  # Settings.WORKER_QUEUES
    job_timeout = 600  # 10 minutes - file processing can take time
    keep_result = settings.WORKER_KEEP_RESULT_SECONDS
    max_tries = settings.WORKER_MAX_TRIES
    health_check_interval = settings.WORKER_HEALTH_CHECK_INTERVAL

    @staticmethod
    async def on_startup(ctx: dict[str, Any]) -> None:
        """Publish worker.started event on worker startup."""
        try:
            redis_url = (
                settings.redis_url_effective
                if hasattr(settings, "redis_url_effective")
                else settings.REDIS_URL
            )
            ctx["events_redis"] = aioredis.from_url(redis_url)
            ctx["worker_queue_name"] = "media"
            await publish_event(ctx["events_redis"], "worker.started", "media")
            ctx["runtime_reporting"] = runtime.start_reporting(
                ctx["events_redis"],
                runtime.report(
                    worker=worker_id(),
                    queue="media",
                    engine="arq",
                    version=runtime.engine_version("arq"),
                    processes=1,
                    concurrency=WorkerSettings.max_jobs,
                ),
            )
        except Exception as e:
            logger.debug(f"Failed to initialize event publishing: {e}")

    @staticmethod
    async def on_shutdown(ctx: dict[str, Any]) -> None:
        """Publish worker.stopped event on worker shutdown."""
        if "events_redis" in ctx:
            await runtime.stop_reporting(
                ctx["events_redis"], ctx.get("runtime_reporting"), worker_id()
            )
            await publish_event(ctx["events_redis"], "worker.stopped", "media")
            await ctx["events_redis"].aclose()

    @staticmethod
    async def on_job_start(ctx: dict[str, Any]) -> None:
        """Publish job.started event when a job begins processing."""
        if "events_redis" in ctx:
            await publish_event(
                ctx["events_redis"],
                "job.started",
                ctx.get("worker_queue_name", "media"),
                {"job_id": str(ctx.get("job_id", "unknown"))},
            )

    @staticmethod
    async def after_job_end(ctx: dict[str, Any]) -> None:
        """Publish job.completed or job.failed event after each job."""
        if "events_redis" not in ctx:
            return

        job_id = str(ctx.get("job_id", "unknown"))
        queue = ctx.get("worker_queue_name", "media")

        # Determine success/failure from arq's stored result
        success = True
        try:
            raw = await ctx["events_redis"].get(result_key_prefix + job_id)
            if raw:
                result = deserialize_result(raw)
                success = result.success
        except Exception:
            pass

        event_type = "job.completed" if success else "job.failed"
        await publish_event(
            ctx["events_redis"],
            event_type,
            queue,
            {"job_id": job_id, "status": "success" if success else "failed"},
        )
