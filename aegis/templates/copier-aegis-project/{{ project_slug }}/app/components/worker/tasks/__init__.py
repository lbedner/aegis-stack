"""Looking a worker task up by name.

The queue modules are the source of truth for what exists; this package
holds the task functions themselves and answers three questions about
them for the API. There is no list kept here, deliberately: services
append their own tasks to the queues, and a second list would go stale
the moment one did.
"""

from collections.abc import Callable
from typing import Any

from app.core.config import get_default_queue


def _registered_tasks() -> dict[str, Any]:
    """Every task the queue modules register, keyed by name."""
    from app.components.worker.registry import discover_worker_queues, queue_tasks

    tasks: dict[str, Any] = {}
    for queue_name in discover_worker_queues():
        tasks.update(queue_tasks(queue_name))
    return tasks


def _underlying_function(task: Any) -> Callable[..., Any]:
    """The plain function behind a queue entry.

    TaskIQ and dramatiq hand out a wrapper; arq keeps the function itself.
    Callers want the function - its name and its docstring live there.
    """
    return getattr(task, "original_func", None) or getattr(task, "fn", None) or task


def get_task_by_name(task_name: str) -> Callable[..., Any] | None:
    """The task function registered under ``task_name``, or None."""
    task = _registered_tasks().get(task_name)
    return _underlying_function(task) if task is not None else None


def list_available_tasks() -> list[str]:
    """Every task name any queue registers."""
    return list(_registered_tasks())


def get_queue_for_task(task_name: str) -> str:
    """The queue that registers ``task_name``, or the default queue."""
    from app.components.worker.registry import discover_worker_queues, queue_tasks

    for queue_name in discover_worker_queues():
        if task_name in queue_tasks(queue_name):
            return queue_name

    return get_default_queue()
