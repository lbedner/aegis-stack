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


def get_task_by_name(task_name: str) -> Callable[..., Any] | None:
    """
    Get task function by name.

    Args:
        task_name: Name of the task function

    Returns:
        Task function or None if not found
    """
    for task_func in TASK_FUNCTIONS:
        if task_func.__name__ == task_name:
            return task_func
    return None


def list_available_tasks() -> list[str]:
    """
    Get list of all available task names.

    Returns:
        List of task function names
    """
    return [task_func.__name__ for task_func in TASK_FUNCTIONS]


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
    # Task to queue mapping
    task_queue_map = {
        # Load test tasks
        "load_test_orchestrator": "load_test",
        "cpu_intensive_task": "load_test",
        "io_simulation_task": "load_test",
        "memory_operations_task": "load_test",
        "failure_testing_task": "load_test",
        # Future system and media tasks would go here
    }

    return task_queue_map.get(
        task_name, get_default_queue()
    )  # Default to configured default queue
