"""One extraction, run as a job, wherever the job runs.

The worker task and the in-process runner both call ``run_extraction``;
they differ only in how progress gets back to whoever is watching, which
is the ``report`` callable each passes in.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from app.core.db import get_async_session
from app.services.documents.domains.extraction.pages import extract_document
from app.services.documents.domains.extraction.vision import vision_reader

# Sync on purpose: extract_document calls it between pages from inside its
# own loop. A store that writes asynchronously schedules the write.
Report = Callable[[str], None]


def progress_label(page: int, total: int) -> str:
    return f"Reading page {page} of {total}..."


async def run_extraction(
    document_id: int,
    *,
    owner_user_id: int | None,
    force: bool,
    report: Report,
) -> dict[str, int]:
    """Extract in its own session; ``report`` receives each page's label."""
    async with get_async_session() as session:
        result = await extract_document(
            session,
            document_id,
            owner_user_id=owner_user_id,
            vision=await vision_reader(),
            force=force,
            progress=lambda page, total: report(progress_label(page, total)),
        )
        await session.commit()
    return result.as_dict()


async def run_extraction_job(
    job_id: str, document_id: int, owner_user_id: int | None, force: bool
) -> dict[str, Any]:
    """The worker's entry: narrate into the shared job store, then finish."""
    from app.core.config import settings
    from app.services.system.job_store import RedisJobStore

    store = RedisJobStore.from_url(settings.REDIS_URL)
    loop = asyncio.get_running_loop()
    # Labels are written without waiting, so the page being read is never
    # held up by Redis - but they are held here, because closing the client
    # out from under a write in flight loses the progress it carried.
    writes: set[asyncio.Task[None]] = set()

    def report(label: str) -> None:
        task = loop.create_task(store.set_label(job_id, label))
        writes.add(task)
        task.add_done_callback(writes.discard)

    try:
        result = await run_extraction(
            document_id, owner_user_id=owner_user_id, force=force, report=report
        )
        await store.finish(job_id, result)
        return result
    except Exception as exc:
        await store.fail(job_id, str(exc) or type(exc).__name__)
        raise
    finally:
        if writes:
            await asyncio.gather(*writes, return_exceptions=True)
        await store.aclose()
