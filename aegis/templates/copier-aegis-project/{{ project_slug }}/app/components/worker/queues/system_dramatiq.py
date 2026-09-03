"""
System worker queue configuration for Dramatiq.

Handles system maintenance and monitoring tasks using Dramatiq patterns.
"""

from datetime import UTC, datetime

# Import broker to ensure it is initialised before actors are registered
import app.components.worker.broker  # noqa: F401
import dramatiq
from app.core.log import logger


@dramatiq.actor(queue_name="system", store_results=True)
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


@dramatiq.actor(queue_name="system", store_results=True)
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


@dramatiq.actor(queue_name="system", store_results=True, time_limit=30 * 60 * 1000)
async def extract_document_task(
    job_id: str, document_id: int, owner_user_id: int | None, force: bool
) -> dict:
    """Read a stored document's pages; progress lands in the shared job store.

    The documents service is imported lazily so a stack without it still
    loads this queue and simply never receives the task.
    """
    from app.services.documents.domains.extraction.jobs import run_extraction_job

    return await run_extraction_job(job_id, document_id, owner_user_id, force)
