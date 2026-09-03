"""Document extraction as a worker task (arq form).

Registered in the system queue so no extra worker process is needed. The
body imports the documents service lazily: a worker stack without the
documents service still imports this module and simply never receives
the task.
"""

from typing import Any


async def extract_document_task(
    ctx: dict[str, Any],
    job_id: str,
    document_id: int,
    owner_user_id: int | None,
    force: bool,
) -> dict[str, Any]:
    from app.services.documents.domains.extraction.jobs import run_extraction_job

    return await run_extraction_job(job_id, document_id, owner_user_id, force)
