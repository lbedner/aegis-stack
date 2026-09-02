"""In-process background jobs with push-style progress.

The dashboard's long operations (a 17k-row file import, an analyst note
that waits on a local model) outlive any sane HTTP timeout. The pattern
here is the standard FastAPI one, minus the polling: an endpoint
validates its input synchronously, starts the real work as an asyncio
task, and returns a job id; ``GET /api/v1/jobs/{id}/events`` then streams
status over SSE until the job lands.

State is process-local by default: without a worker the webserver does
the work, and if it dies the job dies with it. With a worker, a job's
record lives in Redis (``job_store.py``) and the runner answers for ids
it never ran itself, so the callers and the jobs API are the same either
way.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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
    started_at: str = ""  # ISO 8601, UTC; what "newest first" sorts on

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "name": self.name,
            "status": self.status,
            "label": self.label,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
        }


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


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
        "started_at",
    )

    def __init__(self, job_id: str, name: str, label: str) -> None:
        self.job_id = job_id
        self.name = name
        self.started_at = now_iso()
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
            started_at=self.started_at,
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
        self._remote: Any | None = None
        self._poll_seconds = 0.5
        self._relays: dict[int, asyncio.Task[None]] = {}
        # Watchers of every job at once (the Activity tab, a jobs page).
        self._all_subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._relay_all_task: asyncio.Task[None] | None = None

    def attach_remote(self, store: Any, *, poll_seconds: float = 0.5) -> None:
        """Answer for jobs that live in a shared store (a worker's)."""
        self._remote = store
        self._poll_seconds = poll_seconds

    async def lookup(self, job_id: str) -> JobSnapshot | None:
        """Local first, then the shared store if one is attached."""
        local = self.get(job_id)
        if local is not None or self._remote is None:
            return local
        try:
            return await self._remote.get(job_id)
        except Exception as e:  # noqa: BLE001 - an unreachable store is "not found", logged
            logger.warning(f"Job store unreachable: {e}")
            return None

    async def subscribe_any(
        self, job_id: str
    ) -> asyncio.Queue[dict[str, Any] | None] | None:
        """``subscribe`` for a local job, or a polling relay for a remote one."""
        local = self.subscribe(job_id)
        if local is not None or self._remote is None:
            return local
        first = await self.lookup(job_id)
        if first is None:
            return None
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        queue.put_nowait(first.as_dict())
        if first.status != "running":
            queue.put_nowait(None)
            return queue
        self._relays[id(queue)] = asyncio.create_task(
            self._relay(job_id, queue, first.as_dict())
        )
        return queue

    async def _relay(
        self,
        job_id: str,
        queue: asyncio.Queue[dict[str, Any] | None],
        last: dict[str, Any],
    ) -> None:
        """Poll the store, forward changes, stop at the terminal state."""
        assert self._remote is not None
        while True:
            await asyncio.sleep(self._poll_seconds)
            try:
                snapshot = await self._remote.get(job_id)
            except Exception as e:  # noqa: BLE001 - end the stream, don't hang it
                # A watcher blocked on this queue has no other way to learn
                # the store went away: without the sentinel it waits forever.
                logger.warning(f"Job store unreachable while watching {job_id}: {e}")
                queue.put_nowait(None)
                return
            if snapshot is None:
                queue.put_nowait(None)
                return
            current = snapshot.as_dict()
            if current != last:
                queue.put_nowait(current)
                last = current
            if snapshot.status != "running":
                queue.put_nowait(None)
                return

    def start(self, name: str, work: JobWork, *, label: str = "") -> str:
        """Run ``work`` as a background task; returns the job id immediately.

        ``work`` receives a :class:`JobHandle` for label updates and returns
        the job's result payload; a raised exception becomes the job's error
        text (so raise with a message worth showing to a person).
        """
        job = _Job(uuid.uuid4().hex, name, label or name)
        self._jobs[job.job_id] = job
        self._evict()
        self._publish(job)
        job.task = asyncio.create_task(self._run(job, work))
        return job.job_id

    async def list_all(self) -> list[JobSnapshot]:
        """Every job this process knows plus the shared store's, running
        first, then newest first."""
        seen: dict[str, JobSnapshot] = {
            j.job_id: j.snapshot() for j in self._jobs.values()
        }
        for snapshot in await self._remote_jobs():
            seen.setdefault(snapshot.job_id, snapshot)
        return sorted(
            seen.values(),
            key=lambda s: (s.status == "running", s.started_at),
            reverse=True,
        )

    def subscribe_all(self) -> asyncio.Queue[dict[str, Any]]:
        """Every change to every job, local ones as they happen and the
        store's by polling. Never terminates on its own; unsubscribe."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._all_subscribers.append(queue)
        if self._remote is not None and (
            self._relay_all_task is None or self._relay_all_task.done()
        ):
            self._relay_all_task = asyncio.create_task(self._relay_all())
        return queue

    def unsubscribe_all(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        if queue in self._all_subscribers:
            self._all_subscribers.remove(queue)

    async def _relay_all(self) -> None:
        """Poll the store while anyone watches everything; forward changes."""
        last: dict[str, dict[str, Any]] = {}
        while self._all_subscribers:
            for snapshot in await self._remote_jobs():
                if snapshot.job_id in self._jobs:
                    continue  # local jobs publish themselves
                current = snapshot.as_dict()
                if last.get(snapshot.job_id) != current:
                    last[snapshot.job_id] = current
                    for queue in self._all_subscribers:
                        queue.put_nowait(current)
            await asyncio.sleep(self._poll_seconds)

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
        relay = self._relays.pop(id(queue), None)
        if relay is not None:
            # The client that asked for this stream is gone; polling Redis
            # on its behalf until the job ends is work for nobody.
            relay.cancel()

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

    async def _remote_jobs(self) -> list[JobSnapshot]:
        """The store's jobs, or none when there is no store or it is down:
        a Redis outage must not take the jobs list with it."""
        if self._remote is None:
            return []
        try:
            return list(await self._remote.list_jobs())
        except Exception as e:  # noqa: BLE001 - degrade to local jobs, say so once
            logger.warning(f"Job store unreachable: {e}")
            return []

    def _publish(self, job: _Job, final: bool = False) -> None:
        snapshot = job.snapshot().as_dict()
        for watcher in self._all_subscribers:
            watcher.put_nowait(snapshot)
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
