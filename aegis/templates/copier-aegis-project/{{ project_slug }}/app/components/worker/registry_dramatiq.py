"""Worker queue registry for Dramatiq.

A queue is a module that registers actors; its tasks are the actors it
defines. Everything that is not one of those two answers lives in
``queue_discovery``.
"""

from typing import Any

import dramatiq

from app.components.worker import queue_discovery as discovery
from app.core.log import logger


def _is_queue(queue_name: str) -> bool:
    return discovery.queue_module(queue_name) is not None


def _is_task(obj: Any) -> bool:
    return isinstance(obj, dramatiq.Actor)


def discover_worker_queues() -> list[str]:
    """Every importable queue module, sorted."""
    return discovery.discover_queues(_is_queue)


def queue_tasks(queue_name: str) -> dict[str, Any]:
    """Actors the queue module registers, keyed by name."""
    return discovery.module_members(queue_name, _is_task)


def get_queue_metadata(queue_name: str) -> dict[str, Any]:
    """Metadata for a queue: its actors, its limits, and its Redis list."""
    return discovery.build_metadata(
        queue_name,
        list(queue_tasks(queue_name)),
        redis_queue_name=f"dramatiq:{queue_name}",
    )


def get_all_queue_metadata() -> dict[str, dict[str, Any]]:
    """Metadata for every discovered queue, keyed by queue name."""
    return discovery.collect_metadata(discover_worker_queues, get_queue_metadata)


def get_queue_lifecycle(queue_name: str) -> dict[str, dict[str, str]]:
    """The middleware hooks that fire during a worker's lifecycle.

    In Dramatiq these are middleware methods on ``EventPublishMiddleware``.
    """
    from app.components.worker.middleware import EventPublishMiddleware

    return discovery.describe_hooks(
        EventPublishMiddleware,
        {
            "on_startup": "before_worker_boot",
            "on_shutdown": "before_worker_shutdown",
            "on_job_start": "before_process_message",
            "after_job_end": "after_process_message",
        },
    )


def get_task_docstrings(queue_name: str) -> dict[str, dict[str, str]]:
    """Each actor's docstring and where it is defined."""
    return discovery.docstrings_for(
        queue_tasks(queue_name), lambda actor: getattr(actor, "fn", actor)
    )


def validate_queue_name(queue_name: str) -> bool:
    """Whether a queue by this name exists."""
    return queue_name in discover_worker_queues()


__all__ = [
    "discover_worker_queues",
    "get_all_queue_metadata",
    "get_queue_lifecycle",
    "get_queue_metadata",
    "get_task_docstrings",
    "queue_tasks",
    "validate_queue_name",
]

logger.debug("Dramatiq queue registry ready")
