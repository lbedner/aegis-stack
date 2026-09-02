"""
Worker queue registry with dynamic discovery for TaskIQ.

Pure TaskIQ implementation - broker instances are the single source of truth.
No configuration files, no abstractions, just TaskIQ as intended.
"""

import importlib
from pathlib import Path
from typing import Any

from app.core.log import logger


def get_broker(queue_name: str) -> Any:
    """Import and return broker instance for a queue.

    Args:
        queue_name: Name of the queue (e.g., 'system', 'load_test')

    Returns:
        TaskIQ broker instance from the queue module

    Raises:
        ImportError: If queue module doesn't exist
        AttributeError: If broker instance not found
    """
    try:
        module = importlib.import_module(f"app.components.worker.queues.{queue_name}")
        return module.broker
    except ImportError as e:
        logger.error(f"Failed to import worker queue '{queue_name}': {e}")
        raise
    except AttributeError as e:
        logger.error(f"broker instance not found in '{queue_name}' queue: {e}")
        raise


def discover_worker_queues() -> list[str]:
    """Discover all worker queues from the queues directory.

    Scans app/components/worker/queues/ for Python files and treats each
    file as a potential queue. Excludes __init__.py and other non-queue files.

    Returns:
        Sorted list of queue names
    """
    queues_dir = Path(__file__).parent / "queues"

    if not queues_dir.exists():
        logger.warning(f"Worker queues directory not found: {queues_dir}")
        return []

    queue_files = queues_dir.glob("*.py")
    queues = []

    for file in queue_files:
        # Skip __init__.py and other special files
        if file.stem not in ["__init__", "__pycache__"]:
            # Verify the file has a broker instance
            try:
                get_broker(file.stem)
                queues.append(file.stem)
            except (ImportError, AttributeError):
                logger.debug(f"Skipping '{file.stem}' - no valid broker instance")
                continue

    return sorted(queues)


def queue_tasks(queue_name: str) -> dict[str, Any]:
    """Tasks a queue module registers, keyed by name, in definition order.

    Read from the module rather than from a list kept beside it: services
    add their own tasks to these modules, and a hand-kept list silently
    omits them from the dashboard, the health check and the enqueue API
    while the worker runs them perfectly well.
    """
    try:
        module = importlib.import_module(f"app.components.worker.queues.{queue_name}")
    except ImportError:
        logger.warning(f"Queue module not importable: {queue_name}")
        return {}

    return {
        name: obj
        for name, obj in vars(module).items()
        if not name.startswith("_") and hasattr(obj, "kiq")
    }


def get_queue_metadata(queue_name: str) -> dict[str, Any]:
    """Get metadata for a queue.

    Args:
        queue_name: Name of the queue

    Returns:
        Dictionary with queue metadata:
        - queue_name: Queue identifier
        - tasks: List of registered task names
        - description: Human-readable description
    """
    task_names = list(queue_tasks(queue_name))

    metadata = {
        "queue_name": queue_name,
        "stream_name": f"taskiq:{queue_name}",  # Redis stream name for TaskIQ health checks
        "tasks": task_names,
        "task_count": len(task_names),
        "functions": task_names,  # Alias for health check compatibility
        "max_jobs": 10,  # Default concurrency (matches env WORKER_CONCURRENCY)
        "timeout": 300,  # Default timeout in seconds
        "description": f"{queue_name.replace('_', ' ').title()} worker queue",
    }

    return metadata


def get_all_queue_metadata() -> dict[str, dict[str, Any]]:
    """Get metadata for all discovered worker queues.

    Returns:
        Dictionary mapping queue names to their metadata
    """
    metadata = {}
    for queue_name in discover_worker_queues():
        metadata[queue_name] = get_queue_metadata(queue_name)
    return metadata


def get_queue_lifecycle(queue_name: str) -> dict[str, dict[str, str]]:
    """Get lifecycle hook info for a queue.

    Returns the middleware hooks that fire during a worker's lifecycle.
    In TaskIQ, hooks are middleware methods on EventPublishMiddleware.

    Args:
        queue_name: Name of the queue (e.g., 'system', 'load_test')

    Returns:
        Dictionary mapping hook names to their metadata.
    """
    from app.components.worker.middleware import EventPublishMiddleware

    hooks: dict[str, dict[str, str]] = {}
    hook_map = {
        "on_startup": "startup",
        "on_shutdown": "shutdown",
        "on_job_start": "pre_execute",
        "after_job_end": "post_execute",
    }
    for key, method_name in hook_map.items():
        fn = getattr(EventPublishMiddleware, method_name, None)
        if fn and callable(fn):
            hooks[key] = {
                "name": method_name,
                "module": f"{fn.__module__}.EventPublishMiddleware.{method_name}",
                "description": (fn.__doc__ or "").strip(),
            }
    return hooks


def get_task_docstrings(queue_name: str) -> dict[str, dict[str, str]]:
    """Get docstrings and module paths for all tasks in a queue.

    Imports the queue module and extracts docstrings from task functions.
    Handles TaskIQ's @broker.task decorator which preserves __doc__.

    Args:
        queue_name: Name of the queue (e.g., 'system', 'load_test')

    Returns:
        Dict mapping function name to {"description": ..., "module": ...}
    """
    try:
        module = importlib.import_module(f"app.components.worker.queues.{queue_name}")
    except ImportError:
        return {}

    result: dict[str, dict[str, str]] = {}
    metadata = get_queue_metadata(queue_name)
    for func_name in metadata.get("tasks", []):
        obj = getattr(module, func_name, None)
        if obj is None:
            continue
        # TaskIQ preserves __doc__ on decorated tasks; fallback to .fn
        fn = getattr(obj, "fn", obj)
        doc = (fn.__doc__ or "").strip() if hasattr(fn, "__doc__") else ""
        mod = f"{fn.__module__}.{fn.__qualname__}" if hasattr(fn, "__module__") else ""
        if doc or mod:
            result[func_name] = {"description": doc, "module": mod}
    return result


def validate_queue_name(queue_name: str) -> bool:
    """Check if a queue name is valid (has a corresponding broker).

    Args:
        queue_name: Name to validate

    Returns:
        True if queue exists and has valid broker instance
    """
    return queue_name in discover_worker_queues()
