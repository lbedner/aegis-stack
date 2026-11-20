"""Where an extraction job runs: the worker when the stack has one, else here.

The Extract button, the jobs API and the SSE stream never know which. A
job id comes back either way; progress and the result arrive through the
same endpoints.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.log import logger
from app.services.documents.domains.extraction.jobs import run_extraction
from app.services.system.job_store import start_job
from app.services.system.jobs import JobHandle, get_job_runner

# How long a reader that needs the pages now waits on their job.
# ponytail: one bound for every document; a long scan read with vision can
# take longer, so raise it if real ones time out.
WAIT_SECONDS = 300


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


async def read_quietly(document_id: int, *, owner_user_id: int | None) -> None:
    """Read the pages on the worker without anybody asking, and never let
    that fail the thing that filed the document.

    Never forced: a page is read once, and re-filing paper already on
    file must not pay to read it twice. Guarded, because the BYTES are
    the valuable thing - a worker that is down loses the reading, never
    the document, and the reading is offered again from the document.
    """
    try:
        await start_extraction(document_id, owner_user_id=owner_user_id, force=False)
    except Exception:
        logger.exception("documents.extract.not_started", document_id=document_id)


async def extract_and_wait(
    document_id: int, *, owner_user_id: int | None, force: bool
) -> dict[str, Any]:
    """``start_extraction``, waited on: for a reader that needs the pages
    now (a chat turn), so the webserver still renders none where there is
    a worker. The job's result; RuntimeError when it failed or cannot be
    followed from here, TimeoutError past ``WAIT_SECONDS``."""
    job_id = await start_extraction(
        document_id, owner_user_id=owner_user_id, force=force
    )
    runner = get_job_runner()
    queue = await runner.subscribe_any(job_id)
    if queue is None:
        raise RuntimeError(f"Extraction job {job_id} cannot be followed from here")
    last: dict[str, Any] = {}
    async with asyncio.timeout(WAIT_SECONDS):
        async for snapshot in runner.follow(job_id, queue):
            last = snapshot
    if last.get("status") != "done":
        raise RuntimeError(last.get("error") or "The extraction did not finish")
    return last.get("result") or {}
