"""Worker queue registry for arq.

A queue is a module with a ``WorkerSettings`` class, and that class is the
source of truth for what the queue runs and how hard: its ``functions``
list, its concurrency, its timeout, its lifecycle hooks. Everything that
is not one of those answers lives in ``queue_discovery``.
"""

from typing import Any

from app.components.worker import queue_discovery as discovery
from app.core.log import logger


def get_worker_settings(queue_name: str) -> Any:
    """The queue's ``WorkerSettings`` class.

    Raises:
        ImportError: if there is no such queue module
        AttributeError: if the module defines no WorkerSettings
    """
    module = discovery.queue_module(queue_name)
    if module is None:
        logger.error(f"Failed to import worker queue '{queue_name}'")
        raise ImportError(f"No queue module named {queue_name}")
    try:
        return module.WorkerSettings
    except AttributeError as e:
        logger.error(f"WorkerSettings class not found in '{queue_name}' queue: {e}")
        raise


def _is_queue(queue_name: str) -> bool:
    module = discovery.queue_module(queue_name)
    return module is not None and hasattr(module, "WorkerSettings")


def discover_worker_queues() -> list[str]:
    """Every queue module that defines WorkerSettings, sorted."""
    return discovery.discover_queues(_is_queue)


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
    """Metadata for a queue, read from its WorkerSettings.

    ``queue_name`` here is arq's Redis queue name rather than the module's,
    because that is what the settings class calls it and what the health
    check looks for in Redis.
    """
    try:
        settings_class = get_worker_settings(queue_name)
    except (ImportError, AttributeError) as e:
        logger.error(f"Failed to get metadata for queue '{queue_name}': {e}")
        return discovery.build_metadata(
            f"arq:queue:{queue_name}", [], description=f"Unknown queue: {queue_name}"
        )

    doc = (getattr(settings_class, "__doc__", "") or "").strip()
    return discovery.build_metadata(
        getattr(settings_class, "queue_name", f"arq:queue:{queue_name}"),
        list(queue_tasks(queue_name)),
        max_jobs=getattr(settings_class, "max_jobs", discovery.DEFAULT_MAX_JOBS),
        timeout=getattr(
            settings_class, "job_timeout", discovery.DEFAULT_TIMEOUT_SECONDS
        ),
        description=getattr(settings_class, "description", None) or doc or None,
    )


def get_all_queue_metadata() -> dict[str, dict[str, Any]]:
    """Metadata for every discovered queue, keyed by queue name."""
    return discovery.collect_metadata(discover_worker_queues, get_queue_metadata)


def get_queue_lifecycle(queue_name: str) -> dict[str, dict[str, str]]:
    """The hooks arq calls around a worker's life, as the queue defines them."""
    try:
        settings_class = get_worker_settings(queue_name)
    except (ImportError, AttributeError):
        return {}

    return discovery.describe_hooks(
        settings_class,
        {
            "on_startup": "on_startup",
            "on_shutdown": "on_shutdown",
            "on_job_start": "on_job_start",
            "after_job_end": "after_job_end",
        },
    )


def get_task_docstrings(queue_name: str) -> dict[str, dict[str, str]]:
    """Each task's docstring and where it is defined."""
    return discovery.docstrings_for(queue_tasks(queue_name), lambda fn: fn)


def validate_queue_name(queue_name: str) -> bool:
    """Whether a queue by this name exists and has WorkerSettings."""
    return queue_name in discover_worker_queues()


__all__ = [
    "discover_worker_queues",
    "get_all_queue_metadata",
    "get_queue_lifecycle",
    "get_queue_metadata",
    "get_task_docstrings",
    "get_worker_settings",
    "queue_tasks",
    "validate_queue_name",
]

logger.debug("arq queue registry ready")
