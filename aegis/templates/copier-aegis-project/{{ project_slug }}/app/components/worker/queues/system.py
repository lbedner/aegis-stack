"""
System worker queue configuration.

Handles system maintenance and monitoring tasks using native arq patterns.
"""

from typing import Any

import redis.asyncio as aioredis
from app.components.worker.events import publish_event
from app.components.worker.tasks.document_tasks import extract_document_task
from app.components.worker.tasks.simple_system_tasks import (
    cleanup_temp_files,
    system_health_check,
)
from app.core.config import settings
from app.core.log import logger
from arq.connections import RedisSettings
from arq.constants import result_key_prefix
from arq.jobs import deserialize_result


class WorkerSettings:
    """System maintenance worker configuration."""

    # Human-readable description
    description = "System maintenance and monitoring tasks"

    # Task functions for this queue
    functions = [
        system_health_check,
        cleanup_temp_files,
        extract_document_task,
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
    queue_name = "arq:queue:system"
    max_jobs = 15  # Moderate concurrency for administrative operations
    job_timeout = 300  # 5 minutes
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
            ctx["worker_queue_name"] = "system"
            await publish_event(ctx["events_redis"], "worker.started", "system")
        except Exception as e:
            logger.debug(f"Failed to initialize event publishing: {e}")

    @staticmethod
    async def on_shutdown(ctx: dict[str, Any]) -> None:
        """Publish worker.stopped event on worker shutdown."""
        if "events_redis" in ctx:
            await publish_event(ctx["events_redis"], "worker.stopped", "system")
            await ctx["events_redis"].aclose()

    @staticmethod
    async def on_job_start(ctx: dict[str, Any]) -> None:
        """Publish job.started event when a job begins processing."""
        if "events_redis" in ctx:
            job_id = str(ctx.get("job_id", "unknown"))
            await publish_event(
                ctx["events_redis"],
                "job.started",
                ctx.get("worker_queue_name", "system"),
                {"job_id": job_id},
            )
            # Record task started in history
            from app.components.worker.task_history import (
                record_task_started,
                resolve_arq_task_name,
            )

            task_name = await resolve_arq_task_name(ctx["events_redis"], job_id)
            await record_task_started(
                ctx["events_redis"],
                job_id,
                task_name=task_name,
                queue_name="system",
            )

    @staticmethod
    async def after_job_end(ctx: dict[str, Any]) -> None:
        """Publish job.completed or job.failed event after each job."""
        if "events_redis" not in ctx:
            return

        job_id = str(ctx.get("job_id", "unknown"))
        queue = ctx.get("worker_queue_name", "system")

        # Determine success/failure from arq's stored result
        success = True
        error_msg: str | None = None
        task_name: str | None = None
        try:
            raw = await ctx["events_redis"].get(result_key_prefix + job_id)
            if raw:
                result = deserialize_result(raw)
                success = result.success
                task_name = result.function
                if not success and result.result:
                    error_msg = str(result.result)
        except Exception:
            pass

        event_type = "job.completed" if success else "job.failed"
        await publish_event(
            ctx["events_redis"],
            event_type,
            queue,
            {"job_id": job_id, "status": "success" if success else "failed"},
        )
        # Record task finished in history
        from app.components.worker.task_history import record_task_finished

        await record_task_finished(
            ctx["events_redis"],
            job_id,
            success=success,
            error=error_msg,
            task_name=task_name,
            queue_name=queue,
        )
