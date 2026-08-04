"""In-process background jobs with push-style progress.

The dashboard's long operations (a 17k-row file import, an analyst note
that waits on a local model) outlive any sane HTTP timeout. The pattern
here is the standard FastAPI one, minus the polling: an endpoint
validates its input synchronously, starts the real work as an asyncio
task, and returns a job id; ``GET /api/v1/jobs/{id}/events`` then streams
status over SSE until the job lands.

State is process-local on purpose: this stack has no worker component,
so if the webserver dies the job dies with it, and pretending otherwise
would be a lie. A durable queue can slot in behind the same job API
later without the callers changing.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
import uuid

from app.core.log import logger

# Terminal jobs kept around so a late subscriber (a client that asks after
# the work finished) still gets the terminal event. Oldest evicted first.
_DEFAULT_MAX_FINISHED = 200

JobWork = Callable[["JobHandle"], Awaitable[dict[str, Any] | None]]


@dataclass
class JobSnapshot:
    """Point-in-time view of a job, safe to hand to serializers."""

    job_id: str
    name: str
    status: str  # "running" | "done" | "failed"
    label: str
    result: dict[str, Any] | None
    error: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "name": self.name,
            "status": self.status,
            "label": self.label,
            "result": self.result,
            "error": self.error,
        }


class _Job:
    __slots__ = (
        "job_id",
        "name",
        "status",
        "label",
        "result",
        "error",
        "task",
        "subscribers",
    )

    def __init__(self, job_id: str, name: str, label: str) -> None:
        self.job_id = job_id
        self.name = name
        self.status = "running"
        self.label = label
        self.result: dict[str, Any] | None = None
        self.error: str | None = None
        self.task: asyncio.Task[None] | None = None
        self.subscribers: list[asyncio.Queue[dict[str, Any] | None]] = []

    def snapshot(self) -> JobSnapshot:
        return JobSnapshot(
            job_id=self.job_id,
            name=self.name,
            status=self.status,
            label=self.label,
            result=self.result,
            error=self.error,
        )


class JobHandle:
    """Given to job work so it can narrate progress to whoever is watching."""

    def __init__(self, job: _Job, runner: JobRunner) -> None:
        self._job = job
        self._runner = runner

    def set_label(self, label: str) -> None:
        self._job.label = label
        self._runner._publish(self._job)


class JobRunner:
    """Registry + executor for in-process jobs."""

    def __init__(self, max_finished: int = _DEFAULT_MAX_FINISHED) -> None:
        self._jobs: OrderedDict[str, _Job] = OrderedDict()
        self._max_finished = max_finished

    def start(self, name: str, work: JobWork, *, label: str = "") -> str:
        """Run ``work`` as a background task; returns the job id immediately.

        ``work`` receives a :class:`JobHandle` for label updates and returns
        the job's result payload; a raised exception becomes the job's error
        text (so raise with a message worth showing to a person).
        """
        job = _Job(uuid.uuid4().hex, name, label or name)
        self._jobs[job.job_id] = job
        self._evict()
        job.task = asyncio.create_task(self._run(job, work))
        return job.job_id

    def get(self, job_id: str) -> JobSnapshot | None:
        job = self._jobs.get(job_id)
        return job.snapshot() if job else None

    def subscribe(self, job_id: str) -> asyncio.Queue[dict[str, Any] | None] | None:
        """Queue of snapshot dicts, primed with the current state.

        A ``None`` sentinel follows the terminal snapshot; a subscriber to an
        already-finished job gets terminal snapshot + sentinel right away.
        """
        job = self._jobs.get(job_id)
        if job is None:
            return None
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        queue.put_nowait(job.snapshot().as_dict())
        if job.status == "running":
            job.subscribers.append(queue)
        else:
            queue.put_nowait(None)
        return queue

    def unsubscribe(
        self, job_id: str, queue: asyncio.Queue[dict[str, Any] | None]
    ) -> None:
        job = self._jobs.get(job_id)
        if job is not None and queue in job.subscribers:
            job.subscribers.remove(queue)

    async def wait(self, job_id: str) -> JobSnapshot:
        """Await the job's completion (tests and sync-ish callers)."""
        job = self._jobs[job_id]
        if job.task is not None:
            await asyncio.shield(job.task)
        return job.snapshot()

    async def _run(self, job: _Job, work: JobWork) -> None:
        try:
            job.result = await work(JobHandle(job, self))
            job.status = "done"
        except Exception as e:
            logger.exception(f"Job failed: {job.name}")
            job.status = "failed"
            job.error = str(e) or type(e).__name__
        self._publish(job, final=True)

    def _publish(self, job: _Job, final: bool = False) -> None:
        snapshot = job.snapshot().as_dict()
        for queue in job.subscribers:
            queue.put_nowait(snapshot)
            if final:
                queue.put_nowait(None)
        if final:
            job.subscribers.clear()

    def _evict(self) -> None:
        finished = [j for j in self._jobs.values() if j.status != "running"]
        overflow = len(finished) - self._max_finished
        for job in finished[:overflow] if overflow > 0 else []:
            self._jobs.pop(job.job_id, None)


_runner: JobRunner | None = None


def get_job_runner() -> JobRunner:
    """Process-wide job runner singleton."""
    global _runner
    if _runner is None:
        _runner = JobRunner()
    return _runner
