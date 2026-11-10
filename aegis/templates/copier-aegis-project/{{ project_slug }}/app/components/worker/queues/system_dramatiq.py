"""
System worker queue configuration for Dramatiq.

Handles system maintenance and monitoring tasks using Dramatiq patterns.
"""

from datetime import UTC, datetime

import dramatiq

# Import broker to ensure it is initialised before actors are registered
import app.components.worker.broker  # noqa: F401
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
    from app.services.documents.service import run_extraction_job

    return await run_extraction_job(job_id, document_id, owner_user_id, force)


# Registered only where the service is: elsewhere the task reaches nothing.
if present("app.services.documents"):
    extract_document_task = dramatiq.actor(
        queue_name=QueueName.SYSTEM, store_results=True, time_limit=30 * 60 * 1000
    )(extract_document_task)


async def read_photo_task(user_id: str, key: str, media_type: str, title: str) -> dict:
    """Keep a picture shared in chat and read what it showed, into its
    paste index. The AI service is imported lazily, as the documents one is."""
    from app.services.ai.service import read_photo_job

    return {"key": key, "read": await read_photo_job(user_id, key, media_type, title)}


# Registered only where the paste index and documents' vision are.
if present("app.services.ai.domains.chat.pastes") and present("app.services.documents"):
    read_photo_task = dramatiq.actor(queue_name=QueueName.SYSTEM, store_results=True)(
        read_photo_task
    )


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


async def run_evals_task(
    job_id: str, name: str, model: str | None, note: str | None
) -> dict:
    """Run and keep an eval dataset; each case lands in the shared job store.
    The AI service is imported lazily, as the documents one is."""
    from app.services.ai.service import run_evals_job

    return await run_evals_job(job_id, name, model, note)


async def generate_evals_task(
    job_id: str, name: str, about: str, cases: int, like: str | None
) -> dict:
    """Write an eval dataset with the model, run it once and keep what held."""
    from app.services.ai.service import generate_evals_job

    return await generate_evals_job(job_id, name, about, cases, like)


# Registered only where evals keep their runs: elsewhere it reaches nothing.
if present("app.services.ai.domains.evals.jobs"):
    # Never retried: each try is paid model calls, and a failure is an answer.
    evals = dramatiq.actor(
        queue_name=QueueName.SYSTEM,
        store_results=True,
        max_retries=0,
        time_limit=30 * 60 * 1000,
    )
    run_evals_task = evals(run_evals_task)
    generate_evals_task = evals(generate_evals_task)


# The scheduled service jobs, bound here so the registry sees them as this
# queue's tasks. The scheduler enqueues them by these names.
globals().update(service_job_tasks())
