"""
Worker tasks registry.

This module collects all available worker tasks and exports them for the arq worker.
Only includes production-ready, actually useful tasks.
"""

from collections.abc import Callable
from typing import Any

from app.core.config import get_default_queue

from .load_tasks import (
    cpu_intensive_task,
    failure_testing_task,
    io_simulation_task,
    memory_operations_task,
)
from .system_tasks import (
    load_test_orchestrator,
)

# All task functions available to arq workers
TASK_FUNCTIONS: list[Callable[..., Any]] = [
    # Load testing orchestrator
    load_test_orchestrator,
    # Load testing tasks
    cpu_intensive_task,
    io_simulation_task,
    memory_operations_task,
    failure_testing_task,
]


def _registered_tasks() -> dict[str, Any]:
    """Every task the queue modules register, keyed by name.

    The queues are the source of truth. Services append their own tasks to
    them, and a list kept here instead goes stale the moment one does — the
    task runs, and the API that is supposed to offer it says it does not
    exist.
    """
    from app.components.worker.registry import discover_worker_queues, queue_tasks

    tasks: dict[str, Any] = {}
    for queue_name in discover_worker_queues():
        tasks.update(queue_tasks(queue_name))
    return tasks


def _underlying_function(task: Any) -> Callable[..., Any]:
    """The plain function behind a queue entry.

    TaskIQ and dramatiq hand out a wrapper; arq keeps the function itself.
    Callers want the function — its name and its docstring live there.
    """
    return getattr(task, "original_func", None) or getattr(task, "fn", None) or task


def get_task_by_name(task_name: str) -> Callable[..., Any] | None:
    """
    Get task function by name.

    Args:
        task_name: Name of the task function

    Returns:
        Task function or None if not found
    """
    task = _registered_tasks().get(task_name)
    return _underlying_function(task) if task is not None else None


def list_available_tasks() -> list[str]:
    """
    Get list of all available task names.

    Returns:
        List of task function names
    """
    return list(_registered_tasks())


def get_queue_functions(queue_type: str) -> list[Callable[..., Any]]:
    """
    Get task functions specific to a queue type.

    Args:
        queue_type: The functional queue type ("media", "system", "load_test")

    Returns:
        List of task functions appropriate for this queue
    """
    # Function distribution by queue type
    queue_function_map = {
        "system": [
            # System queue is for actual system tasks when needed
            # Currently empty - add real system tasks here when required
        ],
        "media": [
            # Future: Image processing, video encoding, file operations
            # Currently empty - real media tasks will be added here
        ],
        "load_test": [
            # Load testing orchestrator
            load_test_orchestrator,
            # Load testing tasks (synthetic workloads)
            cpu_intensive_task,
            io_simulation_task,
            memory_operations_task,
            failure_testing_task,
        ],
    }

    from typing import cast

    return cast(list[Callable[..., Any]], queue_function_map.get(queue_type, []))


def get_queue_for_task(task_name: str) -> str:
    """
    Get the appropriate queue type for a given task.

    Args:
        task_name: Name of the task function

    Returns:
        Queue type that should handle this task
    """
    from app.components.worker.registry import discover_worker_queues, queue_tasks

    for queue_name in discover_worker_queues():
        if task_name in queue_tasks(queue_name):
            return queue_name

    return get_default_queue()
