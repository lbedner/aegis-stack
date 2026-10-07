"""
System worker queue configuration.

Handles system maintenance and monitoring tasks using native arq patterns.
"""

from arq.connections import RedisSettings

from app.components.worker import arq_hooks
from app.components.worker.tasks.document_tasks import extract_document_task
from app.components.worker.tasks.service_jobs import service_job_tasks
from app.components.worker.tasks.simple_system_tasks import (
    cleanup_temp_files,
    system_health_check,
)
from app.core.config import settings
from app.core.queue_workers import concurrency_for


class WorkerSettings:
    """System maintenance worker configuration."""

    # Human-readable description
    description = "System maintenance and monitoring tasks"

    # Task functions for this queue
    functions = [
        system_health_check,
        cleanup_temp_files,
        extract_document_task,
        *service_job_tasks(),
    ]

    # arq configuration with improved connection settings
    base_settings = RedisSettings.from_dsn(settings.redis_url_effective)
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
    max_jobs = concurrency_for("system")  # Settings.WORKER_QUEUES
    job_timeout = 300  # 5 minutes
    keep_result = settings.WORKER_KEEP_RESULT_SECONDS
    max_tries = settings.WORKER_MAX_TRIES
    health_check_interval = settings.WORKER_HEALTH_CHECK_INTERVAL

    on_startup, on_shutdown, on_job_start, after_job_end = arq_hooks.for_queue(
        "system", max_jobs
    )
