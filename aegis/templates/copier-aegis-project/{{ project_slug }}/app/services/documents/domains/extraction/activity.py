"""Extraction runs as rows: which document, and one sentence for where
each run is. Shared by the Flet Activity tab and the Overseer's Activity
section, so a run reads the same in both. Jobs come from the job runner,
which knows every job whether it ran here or on a worker.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


def extraction_summary(result: dict[str, Any]) -> str:
    """What the snackbar says when a run lands.

    "Extracted", not "read": reading is what a person does to the page
    afterwards, and the count here is of pages this run took text out of.
    A run that missed some says so against the total, since "5 extracted"
    alone hides the two it could not do.
    """
    extracted = int(result.get("read") or 0)
    missed = int(result.get("unread") or 0)
    if extracted == 0 and missed == 0:
        return "Already extracted"
    if missed == 0:
        return f"{extracted} pages extracted" if extracted != 1 else "1 page extracted"
    return f"{extracted} of {extracted + missed} pages extracted"


JOB_PREFIX = "documents-extract:"
# A job still "Queued..." this long has no worker picking it up; say so
# rather than showing a bar that moves and a word that does not.
QUEUED_TOO_LONG_SECONDS = 60


@dataclass
class ActivityRow:
    job_id: str
    document_id: int
    title: str
    detail: str
    running: bool
    failed: bool
    queued: bool
    stalled: bool
    incomplete: bool
    when: str
    started_at: str


def document_id_of(job: dict[str, Any]) -> int | None:
    name = str(job.get("name") or "")
    if not name.startswith(JOB_PREFIX):
        return None
    try:
        return int(name[len(JOB_PREFIX) :])
    except ValueError:
        return None


def _is_queued(job: dict[str, Any]) -> bool:
    """Whether the job is still waiting: no worker has reported on it yet.

    The label is the report. Until one arrives it reads "Queued...", and a
    job nobody has picked up is not a job in progress, however long the
    store has been holding it open.
    """
    return str(job.get("label") or "Queued...").startswith("Queued")


def _started(job: dict[str, Any]) -> datetime | None:
    """When the job was created, or None when the record predates the field."""
    try:
        started = datetime.fromisoformat(str(job.get("started_at") or ""))
    except ValueError:
        return None
    return started if started.tzinfo else started.replace(tzinfo=UTC)


def age_label(started_at: str, now: datetime) -> str:
    """How long ago, in the coarsest unit that still says something.

    Relative rather than a clock time: the table renders on the server, so
    a printed hour would be the container's, not the reader's.
    """
    started = _started({"started_at": started_at})
    if started is None:
        return ""
    seconds = int((now - started).total_seconds())
    if seconds < 45:
        return "just now"
    if seconds < 3600:
        return f"{max(1, seconds // 60)}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _queued_for(job: dict[str, Any], now: datetime) -> int | None:
    """Seconds a job has sat queued, or None when that cannot be known."""
    if not _is_queued(job):
        return None
    started = _started(job)
    if started is None:
        return None
    return int((now - started).total_seconds())


def activity_rows(
    jobs: list[dict[str, Any]], titles: dict[int, str], *, now: datetime | None = None
) -> list[ActivityRow]:
    """Extraction jobs as rows: the document's title, and one sentence for
    where it is. Other services' jobs are not this tab's business."""
    now = now or datetime.now(UTC)
    rows: list[ActivityRow] = []
    for job in jobs:
        document_id = document_id_of(job)
        if document_id is None:
            continue
        status = job.get("status")
        queued = False
        stalled = False
        incomplete = False
        if status == "running":
            detail = str(job.get("label") or "Queued...")
            queued = _is_queued(job)
            waited = _queued_for(job, now)
            if waited is not None and waited >= QUEUED_TOO_LONG_SECONDS:
                detail = f"Queued for {waited // 60}m, no worker has picked it up"
                stalled = True
        elif status == "done":
            result = job.get("result") or {}
            detail = extraction_summary(result)
            # Finished is not the same as done with it: a page a model
            # refused is left unread, and the run reports that quietly.
            incomplete = int(result.get("unread") or 0) > 0
        else:
            detail = str(job.get("error") or "Failed")
        rows.append(
            ActivityRow(
                job_id=str(job.get("job_id")),
                document_id=document_id,
                title=titles.get(document_id, f"Document {document_id}"),
                detail=detail,
                running=status == "running",
                failed=status == "failed",
                queued=queued,
                stalled=stalled,
                incomplete=incomplete,
                when=age_label(str(job.get("started_at") or ""), now),
                started_at=str(job.get("started_at") or ""),
            )
        )
    # Newest first: two runs of the same document are only tellable apart
    # by when they ran.
    rows.sort(key=lambda r: r.started_at, reverse=True)
    return rows
