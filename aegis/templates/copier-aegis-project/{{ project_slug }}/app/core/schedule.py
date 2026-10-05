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
from dataclasses import dataclass
import importlib
from typing import Any

from app.core.discovery import modules_named

# Seconds a worker lets a long job run, where the queue's own limit (five
# minutes) is too short. A ceiling, not a measurement.
LONG_RUNNING = 60 * 60


@dataclass(frozen=True)
class ServiceJob:
    """A job function and when it runs.

    ``trigger`` is passed to ``scheduler.add_job`` as keyword arguments.
    ``timeout`` is how long a worker lets it run; None keeps the queue's.
    """

    func: Callable[[], Awaitable[Any]]
    id: str
    name: str
    trigger: dict[str, Any]
    timeout: int | None = None

    @property
    def task_name(self) -> str:
        """The name the worker registers it under and the scheduler enqueues."""
        return self.func.__name__


def service_jobs() -> tuple[ServiceJob, ...]:
    """Every service's ``JOBS``, in service name order.

    An id or a task name claimed twice is an error, not a silent winner:
    the scheduler keys on the id and the worker on the task name, so the
    second would replace the first.
    """
    import app.services as services

    jobs: list[ServiceJob] = []
    for name in modules_named(services, "scheduled_jobs"):
        declared = getattr(importlib.import_module(name), "JOBS", None)
        if declared is None:
            raise ValueError(f"{name} declares no JOBS")
        jobs.extend(declared)
    for label, keys in (
        ("id", Counter(job.id for job in jobs)),
        ("task", Counter(job.task_name for job in jobs)),
    ):
        for key, count in keys.items():
            if count > 1:
                raise ValueError(f"two scheduled jobs claim {label} '{key}'")
    return tuple(jobs)
