"""
Load test worker queue configuration.

Handles load testing orchestration and synthetic workload tasks using native arq
patterns.
"""

from typing import Any

import redis.asyncio as aioredis
from app.components.worker import runtime
from app.components.worker.events import publish_event
from app.components.worker.heartbeat import worker_id
from app.components.worker.tasks.load_tasks import (
    cpu_intensive_task,
    failure_testing_task,
    io_simulation_task,
    memory_operations_task,
)
from app.components.worker.tasks.system_tasks import (
    load_test_orchestrator,
)
from app.core.config import settings
from app.core.log import logger
from app.core.queue_workers import concurrency_for
from arq.connections import RedisSettings
from arq.constants import result_key_prefix
from arq.jobs import deserialize_result


class WorkerSettings:
    """Load testing worker configuration."""

    # Human-readable description
    description = "Load testing and performance testing"

    # Task functions for this queue
    functions = [
        # Load test orchestrator
        load_test_orchestrator,
        # Synthetic workload tasks
        cpu_intensive_task,
        io_simulation_task,
        memory_operations_task,
        failure_testing_task,
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
    queue_name = "arq:queue:load_test"
    max_jobs = concurrency_for("load_test")  # Settings.WORKER_QUEUES
    job_timeout = 60  # Quick tasks
    keep_result = 60  # Short TTL — load test results are fire-and-forget
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
            ctx["worker_queue_name"] = "load_test"
            await publish_event(ctx["events_redis"], "worker.started", "load_test")
            ctx["runtime_reporting"] = runtime.start_reporting(
                ctx["events_redis"],
                runtime.report(
                    worker=worker_id(),
                    queue="load_test",
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
            await publish_event(ctx["events_redis"], "worker.stopped", "load_test")
            await ctx["events_redis"].aclose()

    @staticmethod
    async def on_job_start(ctx: dict[str, Any]) -> None:
        """Publish job.started event when a job begins processing."""
        if "events_redis" in ctx:
            job_id = str(ctx.get("job_id", "unknown"))
            await publish_event(
                ctx["events_redis"],
                "job.started",
                ctx.get("worker_queue_name", "load_test"),
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
                queue_name="load_test",
            )

    @staticmethod
    async def after_job_end(ctx: dict[str, Any]) -> None:
        """Publish job.completed or job.failed event after each job."""
        if "events_redis" not in ctx:
            return

        job_id = str(ctx.get("job_id", "unknown"))
        queue = ctx.get("worker_queue_name", "load_test")

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
