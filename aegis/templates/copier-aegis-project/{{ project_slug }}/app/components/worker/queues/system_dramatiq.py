"""
System worker queue configuration for Dramatiq.

Handles system maintenance and monitoring tasks using Dramatiq patterns.
"""

from datetime import UTC, datetime

# Import broker to ensure it is initialised before actors are registered
import app.components.worker.broker  # noqa: F401
import dramatiq
from app.components.worker.tasks.service_jobs import service_job_tasks
from app.core.constants import QueueName
from app.core.discovery import present
from app.core.log import logger


@dramatiq.actor(queue_name=QueueName.SYSTEM, store_results=True)
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


@dramatiq.actor(queue_name=QueueName.SYSTEM, store_results=True)
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


async def extract_document_task(
    job_id: str, document_id: int, owner_user_id: int | None, force: bool
) -> dict:
    """Read a stored document's pages; progress lands in the shared job store.

    The documents service is imported lazily, so the worker boots
    without loading it.
    """
    from app.services.documents.domains.extraction.jobs import run_extraction_job

    return await run_extraction_job(job_id, document_id, owner_user_id, force)


# Registered only where the service is: elsewhere the task reaches nothing.
if present("app.services.documents"):
    extract_document_task = dramatiq.actor(
        queue_name=QueueName.SYSTEM, store_results=True, time_limit=30 * 60 * 1000
    )(extract_document_task)


async def embed_files_task(key: str, n: int, files: list[str]) -> None:
    """Read, chunk and embed a batch of files for the knowledge base; the
    vectors go back through Redis to the one process that writes the index.
    The RAG service is imported lazily, as the documents one is."""
    from app.services.rag.embedding import embed_batch

    await embed_batch(key, n, files)


# Registered only where the service is: elsewhere the task reaches nothing.
if present("app.services.rag"):
    embed_files_task = dramatiq.actor(
        queue_name=QueueName.SYSTEM, time_limit=30 * 60 * 1000
    )(embed_files_task)


# The scheduled service jobs, bound here so the registry sees them as this
# queue's tasks. The scheduler enqueues them by these names.
globals().update(service_job_tasks())
