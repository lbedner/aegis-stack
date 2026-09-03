"""Worker queue registry for TaskIQ.

Broker instances are the single source of truth: a queue is a module with
one, and its tasks are the members that can be kicked. Everything that is
not one of those two answers lives in ``queue_discovery``.
"""

from typing import Any

from app.components.worker import queue_discovery as discovery
from app.core.log import logger


def get_broker(queue_name: str) -> Any:
    """Import and return the broker instance for a queue.

    Args:
        queue_name: Name of the queue (e.g., 'system', 'load_test')

    Returns:
        TaskIQ broker instance from the queue module

    Raises:
        ImportError: If queue module doesn't exist
        AttributeError: If broker instance not found
    """
    module = discovery.queue_module(queue_name)
    if module is None:
        raise ImportError(f"No queue module named {queue_name}")
    return module.broker


def _is_queue(queue_name: str) -> bool:
    module = discovery.queue_module(queue_name)
    return module is not None and hasattr(module, "broker")


def _is_task(obj: Any) -> bool:
    """A TaskIQ task is anything that can be kicked."""
    return hasattr(obj, "kiq")


def discover_worker_queues() -> list[str]:
    """Every queue module that carries a broker, sorted."""
    return discovery.discover_queues(_is_queue)


def queue_tasks(queue_name: str) -> dict[str, Any]:
    """Tasks the queue module registers, keyed by name."""
    return discovery.module_members(queue_name, _is_task)


def get_queue_metadata(queue_name: str) -> dict[str, Any]:
    """Metadata for a queue: its tasks, its limits, and its Redis stream."""
    return discovery.build_metadata(
        queue_name,
        list(queue_tasks(queue_name)),
        stream_name=f"taskiq:{queue_name}",
    )


def get_all_queue_metadata() -> dict[str, dict[str, Any]]:
    """Metadata for every discovered queue, keyed by queue name."""
    return discovery.collect_metadata(discover_worker_queues, get_queue_metadata)


def get_queue_lifecycle(queue_name: str) -> dict[str, dict[str, str]]:
    """The middleware hooks that fire during a worker's lifecycle.

    In TaskIQ these are middleware methods on ``EventPublishMiddleware``.
    """
    from app.components.worker.middleware import EventPublishMiddleware

    return discovery.describe_hooks(
        EventPublishMiddleware,
        {
            "on_startup": "startup",
            "on_shutdown": "shutdown",
            "on_job_start": "pre_execute",
            "after_job_end": "post_execute",
        },
    )


def get_task_docstrings(queue_name: str) -> dict[str, dict[str, str]]:
    """Each task's docstring and where it is defined."""
    return discovery.docstrings_for(
        queue_tasks(queue_name), lambda task: getattr(task, "original_func", task)
    )


def validate_queue_name(queue_name: str) -> bool:
    """Whether a queue by this name exists and has a broker."""
    return queue_name in discover_worker_queues()


__all__ = [
    "discover_worker_queues",
    "get_all_queue_metadata",
    "get_broker",
    "get_queue_lifecycle",
    "get_queue_metadata",
    "get_task_docstrings",
    "queue_tasks",
    "validate_queue_name",
]

logger.debug("TaskIQ queue registry ready")
