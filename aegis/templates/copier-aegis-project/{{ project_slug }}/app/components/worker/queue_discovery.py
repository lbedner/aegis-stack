"""What every worker backend's registry does the same way.

The three backends differ in what a queue *is* - arq has a
``WorkerSettings`` class, TaskIQ and dramatiq have a broker - and in what
a task looks like once registered. They do not differ in how a queue is
found, how its metadata is shaped for the dashboard, or how a docstring
is read off a task, and writing those three times is how the task lists
they replaced went stale in two places at once.

A backend registry supplies the parts that are actually its own: a
predicate saying whether a module is one of its queues, a predicate
saying whether a member is one of its tasks, and the names its middleware
hooks go by. Everything else is here.
"""

from collections.abc import Callable
import importlib
from pathlib import Path
from typing import Any

from app.core.log import logger

QUEUES_PACKAGE = "app.components.worker.queues"
DEFAULT_MAX_JOBS = 10
DEFAULT_TIMEOUT_SECONDS = 300


def queue_module(queue_name: str) -> Any | None:
    """The imported queue module, or None when there is no such queue."""
    try:
        return importlib.import_module(f"{QUEUES_PACKAGE}.{queue_name}")
    except ImportError:
        return None


def discover_queues(is_queue: Callable[[str], bool]) -> list[str]:
    """Every queue name in ``queues/`` that ``is_queue`` accepts, sorted.

    A file in that directory is a candidate; whether it is really a queue
    is the backend's question, since the answer is a broker for one and a
    settings class for another.
    """
    queues_dir = Path(__file__).parent / "queues"
    if not queues_dir.exists():
        logger.warning(f"Worker queues directory not found: {queues_dir}")
        return []

    queues = []
    for file in queues_dir.glob("*.py"):
        if file.stem in ("__init__", "__pycache__"):
            continue
        if is_queue(file.stem):
            queues.append(file.stem)
        else:
            logger.debug(f"Skipping '{file.stem}' - not a queue for this backend")
    return sorted(queues)


def module_members(queue_name: str, is_task: Callable[[Any], bool]) -> dict[str, Any]:
    """The queue module's own tasks, keyed by name, in definition order.

    Read from the module rather than from a list kept beside it: services
    add their own tasks to these modules, and a hand-kept list silently
    omits them from the dashboard, the health check and the enqueue API
    while the worker runs them perfectly well.
    """
    module = queue_module(queue_name)
    if module is None:
        logger.warning(f"Queue module not importable: {queue_name}")
        return {}

    return {
        name: obj
        for name, obj in vars(module).items()
        if not name.startswith("_") and is_task(obj)
    }


def build_metadata(
    queue_name: str,
    task_names: list[str],
    *,
    max_jobs: int = DEFAULT_MAX_JOBS,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    description: str | None = None,
    **backend_fields: Any,
) -> dict[str, Any]:
    """The shape the dashboard and the health check both read.

    ``functions`` is the same list as ``tasks`` under the name the health
    check has always used. ``backend_fields`` carries what only one
    backend has - a stream name, a Redis list name.
    """
    return {
        "queue_name": queue_name,
        "tasks": task_names,
        "task_count": len(task_names),
        "functions": task_names,
        "max_jobs": max_jobs,
        "timeout": timeout,
        "description": description or f"{queue_name.replace('_', ' ').title()} worker queue",
        **backend_fields,
    }


def collect_metadata(
    discover: Callable[[], list[str]],
    metadata_for: Callable[[str], dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Metadata for every discovered queue, keyed by queue name."""
    return {name: metadata_for(name) for name in discover()}


def describe_hooks(source: Any, hook_map: dict[str, str]) -> dict[str, dict[str, str]]:
    """The lifecycle hooks the dashboard lists, read off whatever defines them.

    arq puts them on the queue's ``WorkerSettings``; TaskIQ and dramatiq put
    them on the event middleware. Either way the entry is the same three
    fields, and ``__qualname__`` already carries the owning class.
    """
    hooks: dict[str, dict[str, str]] = {}
    for key, attribute in hook_map.items():
        fn = getattr(source, attribute, None)
        if fn is None or not callable(fn):
            continue
        hooks[key] = {
            "name": attribute,
            "module": f"{getattr(fn, '__module__', '')}.{getattr(fn, '__qualname__', attribute)}",
            "description": (fn.__doc__ or "").strip(),
        }
    return hooks


def docstrings_for(tasks: dict[str, Any], unwrap: Callable[[Any], Any]) -> dict[
    str, dict[str, str]
]:
    """Each task's first-line docstring and where it is defined.

    ``unwrap`` turns a backend's task object back into the function it
    decorated; the docstring lives there, not on the wrapper.
    """
    result: dict[str, dict[str, str]] = {}
    for name, task in tasks.items():
        fn = unwrap(task)
        doc = (getattr(fn, "__doc__", "") or "").strip()
        module = getattr(fn, "__module__", "")
        qualname = getattr(fn, "__qualname__", "")
        path = f"{module}.{qualname}" if module and qualname else ""
        if doc or path:
            result[name] = {"description": doc, "module": path}
    return result
