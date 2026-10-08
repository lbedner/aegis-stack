"""
Media worker queue configuration.

Handles image processing, file operations, and media transformations using native
arq patterns.
"""

from typing import Any

from arq.connections import RedisSettings

from app.components.worker import arq_hooks
from app.core.config import settings
from app.core.constants import QueueName
from app.core.queue_workers import concurrency_for

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
    queue_name = "arq:queue:media"
    max_jobs = concurrency_for(QueueName.MEDIA)  # Settings.WORKER_QUEUES
    job_timeout = 600  # 10 minutes - file processing can take time
    keep_result = settings.WORKER_KEEP_RESULT_SECONDS
    max_tries = settings.WORKER_MAX_TRIES
    health_check_interval = settings.WORKER_HEALTH_CHECK_INTERVAL

    on_startup, on_shutdown, on_job_start, after_job_end = arq_hooks.for_queue(
        QueueName.MEDIA, max_jobs
    )
