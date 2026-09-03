"""
System worker queue configuration for TaskIQ.

Handles system maintenance and monitoring tasks using TaskIQ patterns.
"""

from datetime import UTC, datetime

from taskiq_redis import RedisAsyncResultBackend

from app.components.worker.broker import PausableRedisStreamBroker
from app.components.worker.middleware import EventPublishMiddleware
from app.core.config import settings
from app.core.log import logger

# Use redis_url_effective for Docker vs local auto-detection
redis_url = (
    settings.redis_url_effective
    if hasattr(settings, "redis_url_effective")
    else settings.REDIS_URL
)

# Create the broker with Redis backend (using streams for acknowledgement support)
# Use unique queue_name to ensure workers don't consume from each other's streams
broker = (
    # ``consumer_id="0"``: a group created at "$" starts at the tail, so
    # anything enqueued before the worker's first successful start is
    # skipped forever - the job sits queued and no worker ever sees it.
    # Starting at "0" hands a new group the backlog it was created to work.
    PausableRedisStreamBroker(
        url=redis_url, queue_name="taskiq:system", consumer_id="0"
    )
    .with_result_backend(
        RedisAsyncResultBackend(redis_url=redis_url, result_ex_time=60)
    )
    .with_middlewares(EventPublishMiddleware().set_queue_name("system"))
)


@broker.task
async def system_health_check() -> dict[str, str]:
    """Verify worker connectivity and responsiveness.

    Returns a timestamped health status to confirm the worker process
    is alive and can execute tasks. Used by the scheduler for periodic
    liveness monitoring.
    """
    logger.debug("Running system health check task")

    return {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "task": "system_health_check",
    }


@broker.task
async def cleanup_temp_files() -> dict[str, str]:
    """Remove stale temporary files from the working directory.

    Placeholder for application-specific cleanup logic. Scans for
    expired temp files, upload artifacts, and cache entries.
    """
    logger.info("Running temp file cleanup task")

    return {
        "status": "completed",
        "timestamp": datetime.now(UTC).isoformat(),
        "task": "cleanup_temp_files",
    }


@broker.task
async def extract_document_task(
    job_id: str, document_id: int, owner_user_id: int | None, force: bool
) -> dict:
    """Read a stored document's pages; progress lands in the shared job store.

    The documents service is imported lazily so a stack without it still
    loads this queue and simply never receives the task.
    """
    from app.services.documents.domains.extraction.jobs import run_extraction_job

    return await run_extraction_job(job_id, document_id, owner_user_id, force)
