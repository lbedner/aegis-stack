"""
Worker queue registry with dynamic discovery.

Pure arq implementation - WorkerSettings classes are the single source of truth.
No configuration files, no abstractions, just arq as intended.
"""

import importlib
from pathlib import Path
from typing import Any

from app.core.log import logger


def get_worker_settings(queue_name: str) -> Any:
    """Import and return WorkerSettings class for a queue.

    Args:
        queue_name: Name of the queue (e.g., 'system', 'load_test')

    Returns:
        WorkerSettings class from the queue module

    Raises:
        ImportError: If queue module doesn't exist
        AttributeError: If WorkerSettings class not found
    """
    try:
        module = importlib.import_module(f"app.components.worker.queues.{queue_name}")
        return module.WorkerSettings
    except ImportError as e:
        logger.error(f"Failed to import worker queue '{queue_name}': {e}")
        raise
    except AttributeError as e:
        logger.error(f"WorkerSettings class not found in '{queue_name}' queue: {e}")
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
            # Verify the file has a WorkerSettings class
            try:
                get_worker_settings(file.stem)
                queues.append(file.stem)
            except (ImportError, AttributeError):
                logger.debug(f"Skipping '{file.stem}' - no valid WorkerSettings class")
                continue

    return sorted(queues)


def queue_tasks(queue_name: str) -> dict[str, Any]:
    """Tasks a queue registers, keyed by name.

    ``WorkerSettings.functions`` is the queue's own list, so services that
    append their tasks to it are visible here without a second list to keep
    in step.
    """
    try:
        settings_class = get_worker_settings(queue_name)
    except (ImportError, AttributeError) as e:
        logger.warning(f"Failed to read tasks for queue '{queue_name}': {e}")
        return {}

    return {fn.__name__: fn for fn in getattr(settings_class, "functions", [])}


def get_queue_metadata(queue_name: str) -> dict[str, Any]:
    """Get metadata for a queue from its WorkerSettings class.

    Args:
        queue_name: Name of the queue

    Returns:
        Dictionary with queue metadata:
        - queue_name: Redis queue name
        - max_jobs: Maximum concurrent jobs
        - timeout: Job timeout in seconds
        - functions: List of function names in this queue
        - description: Human-readable description (if available)
    """
    try:
        settings_class = get_worker_settings(queue_name)

        metadata = {
            "queue_name": getattr(
                settings_class, "queue_name", f"arq:queue:{queue_name}"
            ),
            "max_jobs": getattr(settings_class, "max_jobs", 10),
            "timeout": getattr(settings_class, "job_timeout", 300),
            "functions": list(queue_tasks(queue_name)),
        }

        # Add description if available
        if hasattr(settings_class, "description"):
            metadata["description"] = settings_class.description
        elif hasattr(settings_class, "__doc__") and settings_class.__doc__:
            metadata["description"] = settings_class.__doc__.strip()
        else:
            metadata["description"] = (
                f"{queue_name.replace('_', ' ').title()} worker queue"
            )

        return metadata

    except (ImportError, AttributeError) as e:
        logger.error(f"Failed to get metadata for queue '{queue_name}': {e}")
        return {
            "queue_name": f"arq:queue:{queue_name}",
            "max_jobs": 10,
            "timeout": 300,
            "functions": [],
            "description": f"Unknown queue: {queue_name}",
        }


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

    In arq, lifecycle hooks are defined on the WorkerSettings class
    (on_startup, on_shutdown, on_job_start, after_job_end).

    Args:
        queue_name: Name of the queue (e.g., 'system', 'load_test')

    Returns:
        Dictionary mapping hook names to their metadata.
    """
    try:
        settings_class = get_worker_settings(queue_name)
    except (ImportError, AttributeError):
        return {}

    hooks: dict[str, dict[str, str]] = {}
    hook_names = ["on_startup", "on_shutdown", "on_job_start", "after_job_end"]

    for hook_name in hook_names:
        fn = getattr(settings_class, hook_name, None)
        if fn and callable(fn):
            hooks[hook_name] = {
                "name": fn.__name__,
                "module": f"{fn.__module__}.{fn.__qualname__}",
                "description": (fn.__doc__ or "").strip(),
            }

    return hooks


def get_task_docstrings(queue_name: str) -> dict[str, dict[str, str]]:
    """Get docstrings and module paths for all tasks in a queue.

    In arq, task functions are listed in WorkerSettings.functions.

    Args:
        queue_name: Name of the queue (e.g., 'system', 'load_test')

    Returns:
        Dict mapping function name to {"description": ..., "module": ...}
    """
    try:
        settings_class = get_worker_settings(queue_name)
    except (ImportError, AttributeError):
        return {}

    result: dict[str, dict[str, str]] = {}
    for fn in getattr(settings_class, "functions", []):
        doc = (fn.__doc__ or "").strip() if hasattr(fn, "__doc__") else ""
        mod = f"{fn.__module__}.{fn.__qualname__}" if hasattr(fn, "__module__") else ""
        if doc or mod:
            result[fn.__name__] = {"description": doc, "module": mod}
    return result


def validate_queue_name(queue_name: str) -> bool:
    """Check if a queue name is valid (has a corresponding WorkerSettings).

    Args:
        queue_name: Name to validate

    Returns:
        True if queue exists and has valid WorkerSettings
    """
    return queue_name in discover_worker_queues()
