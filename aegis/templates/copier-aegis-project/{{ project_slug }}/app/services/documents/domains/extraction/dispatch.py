"""Where an extraction job runs: the worker when the stack has one, else here.

The Extract button, the jobs API and the SSE stream never know which. A
job id comes back either way; progress and the result arrive through the
same endpoints.
"""

from __future__ import annotations

from app.core.log import logger
from app.services.documents.domains.extraction.jobs import run_extraction
from app.services.system.job_store import start_job
from app.services.system.jobs import JobHandle, get_job_runner


async def start_extraction_in_process(
    document_id: int, *, owner_user_id: int | None, force: bool
) -> str:
    """Run the extraction as an asyncio task in this process."""

    async def work(handle: JobHandle) -> dict[str, int]:
        return await run_extraction(
            document_id,
            owner_user_id=owner_user_id,
            force=force,
            report=handle.set_label,
        )

    return get_job_runner().start(
        f"documents-extract:{document_id}", work, label="Opening the document..."
    )


async def start_extraction(
    document_id: int, *, owner_user_id: int | None, force: bool
) -> str:
    """Start the extraction as a job: on the worker where the stack has one."""
    job_id = await start_job(
        f"documents-extract:{document_id}",
        "extract_document_task",
        (document_id, owner_user_id, force),
        lambda report: run_extraction(
            document_id, owner_user_id=owner_user_id, force=force, report=report
        ),
        label="Opening the document...",
    )
    logger.info("documents.extract.started", job_id=job_id, document_id=document_id)
    return job_id
