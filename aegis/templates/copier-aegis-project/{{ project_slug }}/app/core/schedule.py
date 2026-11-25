"""The jobs this project runs on a schedule, declared by their services.

Each service lists its jobs in ``app/services/<service>/scheduled_jobs.py`` as
``JOBS``, a tuple of ``ServiceJob``; ``service_jobs`` collects every one.
The scheduler schedules each entry and, in a stack with a worker, the
worker registers each as a task named after its function, so the two read
one list and cannot drift apart. Found on disk through
``app.core.discovery``. The heartbeat is not here: it belongs to the
scheduler.
"""

from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, TypeVar

from structlog.contextvars import bound_contextvars

from app.core.discovery import declared_by, present
from app.core.log import logger
from app.core.log_attribution import remember_exception_origin

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

Item = TypeVar("Item")

# Seconds a worker lets a long job run, where the queue's own limit
# (``QueueWorker.timeout_seconds``) is too short. A ceiling, not a measurement.
LONG_RUNNING = 60 * 60
# A sweep's items are queued on the worker, a task each; a stack without
# one does each item in the sweep itself.
QUEUED = present("app.components.worker")
# An item stays claimed this long: one still waiting in the queue is not
# queued twice, one whose task failed is queued again by a later sweep.
# ponytail: one hold for every sweep; a field per job once one runs more
# often than this.
_CLAIM_SECONDS = 15 * 60


class SweepFailedError(Exception):
    """Items of a sweep done in the sweep failed (each logged), so its run
    is recorded as failed though the rest were done."""


async def read_items(
    read: Callable[["AsyncSession"], Awaitable[list[Item]]],
) -> list[Item]:
    """A sweep's items (its ``func``), read in a session of its own that
    takes no write lock."""
    from app.core.db import get_async_session

    async with get_async_session(read_only=True) as session:
        return await read(session)


@dataclass(frozen=True)
class ServiceJob:
    """A job function and when it runs.

    ``trigger`` is passed to ``scheduler.add_job`` as keyword arguments.
    ``timeout`` is how long a worker lets it run; None keeps the queue's.
    ``server_only``: it reaches real banks, inboxes or storage, so a dev
    stack never schedules it - the server's data is the server's.
    ``at_start``: it also runs as the scheduler starts, so a deploy's
    change shows at once rather than at its next run.
    ``each``: a sweep. ``func`` returns the items (owners, connections) and
    ``each`` does one: the scheduler runs the sweep, which queues a worker
    task per item (``each_task_name``), so one slow or failing item holds
    up none of the rest.
    """

    func: Callable[[], Awaitable[Any]]
    id: str
    name: str
    trigger: dict[str, Any]
    timeout: int | None = None
    server_only: bool = False
    app_service: str | None = None
    at_start: bool = False
    each: Callable[[Any], Awaitable[Any]] | None = None

    async def run(self) -> Any:
        """Execute with the discovered owner, restoring context even on
        failure: the job, or, for a sweep, its items handed out (how many)."""
        return await self._as_service(self._sweep() if self.each else self.func())

    async def fire(self) -> Any:
        """One scheduled run: the job's task queued for the worker, which
        does the work; a sweep, or any job in a stack with no worker, run
        here (a sweep's items still go to the worker)."""
        if not self.runs_here:
            from app.components.worker.pools import enqueue_task
            from app.core.constants import QueueName

            return await enqueue_task(self.task_name, QueueName.SYSTEM)
        return await self.run()

    async def run_each(self, item: Any) -> Any:
        """A sweep's one item, as its owning service (the worker's task)."""
        assert self.each is not None, f"{self.id} is not a sweep"
        return await self._as_service(self.each(item))

    async def _each_here(self, item: Any) -> bool:
        """One item done in the sweep (a stack with no worker), its failure
        logged and kept from the rest, as its own task's would be."""
        try:
            await self.run_each(item)
        except Exception:
            logger.exception("Scheduled job item failed", job=self.id, item=str(item))
            return False
        return True

    async def _as_service(self, work: Awaitable[Any]) -> Any:
        with bound_contextvars(app_service=self.app_service):
            try:
                return await work
            except Exception as error:
                remember_exception_origin(error, self.app_service)
                raise

    async def _sweep(self) -> int:
        """Each item queued once for the worker, or, with none, done here:
        how many. Done here, any item failing fails the run."""
        items = await self.func()
        if not QUEUED:
            done = [await self._each_here(item) for item in items]
            if failed := done.count(False):
                raise SweepFailedError(f"{failed} of {len(items)} items failed")
            return len(done)
        from app.components.worker.queue_once import enqueue_once
        from app.core.constants import QueueName

        queued = 0
        for item in items:
            key = f"schedule:{self.id}:{item}"
            queued += await enqueue_once(
                key, _CLAIM_SECONDS, self.each_task_name, QueueName.SYSTEM, item
            )
        return queued

    @property
    def task_name(self) -> str:
        """The name the worker registers it under and the scheduler enqueues."""
        return self.func.__name__

    @property
    def each_task_name(self) -> str:
        """The task one of a sweep's items runs as."""
        return f"{self.task_name}_each"

    @property
    def handed_to(self) -> str:
        """The task the worker registers for it and the scheduler queues:
        the job's own, or a sweep's per item (the sweep itself runs in the
        scheduler)."""
        return self.each_task_name if self.each else self.task_name

    @property
    def work(
        self,
    ) -> tuple[Callable[..., Awaitable[Any]], Callable[..., Awaitable[Any]]]:
        """What the ``handed_to`` task runs, as ``(code, call)``: the code
        it is named for and the call that runs it as its service."""
        return (self.each, self.run_each) if self.each else (self.func, self.run)

    @property
    def runs_here(self) -> bool:
        """Whether a run happens in the process that fires it (``fire``):
        a sweep, or any job in a stack with no worker."""
        return bool(self.each) or not QUEUED


def service_jobs() -> tuple[ServiceJob, ...]:
    """Every service's ``JOBS``, in service name order.

    An id or a task name claimed twice is an error, not a silent winner:
    the scheduler keys on the id and the worker on the task name, so the
    second would replace the first.
    """
    import app.services as services

    # The folder owns the job, a plugin's too, registered or not yet.
    jobs = [
        replace(job, app_service=owner)
        for owner, declared in declared_by(services, "scheduled_jobs", "JOBS")
        for job in declared
    ]
    for label, keys in (
        ("id", Counter(job.id for job in jobs)),
        ("task", Counter(job.handed_to for job in jobs)),
    ):
        for key, count in keys.items():
            if count > 1:
                raise ValueError(f"two scheduled jobs claim {label} '{key}'")
    return tuple(jobs)


async def fire_service_job(job_id: str) -> Any:
    """Importable scheduler entry point (``ServiceJob.fire``); resolve
    ownership from discovery."""
    for job in service_jobs():
        if job.id == job_id:
            return await job.fire()
    raise ValueError(f"Unknown service job {job_id!r}")
