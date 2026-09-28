"""The worker task pattern, detected from the queues' registries.

Every engine's registry answers ``queue_tasks(queue)``; each engine wraps
the function it runs differently (TaskIQ's ``original_func``, Dramatiq's
``fn``, arq's ``coroutine``), and ``unwrap`` reaches it. The pattern
itself is engine-free: arguments that cross the broker as JSON, a thin
task handing the work to a service, and a JSON result.
"""

from dataclasses import dataclass
import inspect
import types
import typing
from typing import Any

from app.services.system.patterns import (
    THIN_STATEMENTS,
    Pattern,
    Rule,
    Step,
    calls_service,
    returns,
    statement_count,
    thin,
)

JSON_TYPES = (str, int, float, bool, type(None), dict, list)


@dataclass(frozen=True)
class Task:
    queue: str
    name: str
    func: Any


def unwrap(task: Any) -> Any:
    """The function an engine's task object runs."""
    for attr in ("original_func", "fn", "coroutine"):
        func = getattr(task, attr, None)
        if callable(func):
            return func
    return task


def tasks(_source: Any = None) -> list[tuple[str, Task]]:
    """Every task every queue registers, as ``queue.name``."""
    from app.components.worker import registry

    return [
        (f"{queue}.{name}", Task(queue, name, unwrap(task)))
        for queue in registry.discover_worker_queues()
        for name, task in registry.queue_tasks(queue).items()
    ]


def _json(annotation: object, inside: bool = False) -> bool:
    """A type that crosses a broker or a result backend as plain JSON.
    ``Any`` passes only inside a container: ``dict[str, Any]`` is the
    usual JSON object, a bare ``Any`` says nothing."""
    if annotation in JSON_TYPES or (inside and annotation is typing.Any):
        return True
    # A str or int enum serializes as its value.
    if isinstance(annotation, type) and issubclass(annotation, str | int | float):
        return True
    origin = typing.get_origin(annotation)
    if origin in (list, dict, tuple):
        return all(
            _json(a, True) for a in typing.get_args(annotation) if a is not Ellipsis
        )
    if origin in (typing.Union, types.UnionType):
        return all(_json(a, inside) for a in typing.get_args(annotation))
    return False


def _json_args(task: Task) -> bool:
    try:
        hints = typing.get_type_hints(task.func)
    except (NameError, TypeError):
        return False
    params = inspect.signature(task.func).parameters.values()
    # ``*args: T`` and ``**kwargs: T`` cross as a list or dict of T.
    variadic = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    return all(
        p.name in hints and _json(hints[p.name], inside=p.kind in variadic)
        for p in params
    )


def _json_result(task: Task) -> bool:
    return _json(returns(task.func))


def _uses_service(task: Task) -> bool:
    return calls_service(task.func)


def _rank(task: Task) -> tuple[bool, int]:
    """Taking arguments, in the fewest statements."""
    return (bool(inspect.signature(task.func).parameters), -statement_count(task.func))


TASK = Pattern(
    key="task",
    title="Worker task",
    summary=(
        "Work that runs off the request: enqueued by name, carried by the "
        "queue's broker, run by a worker at the queue's configured concurrency. "
        "The task takes plain JSON arguments, hands the work to a service, and "
        "returns a JSON result."
    ),
    steps=(
        Step("Enqueue", "By name, from a route, job or CLI"),
        Step("Broker", "One Redis stream per queue"),
        Step("Worker", "WORKER_QUEUES[queue].concurrency at once"),
        Step(
            "Arguments", "Plain JSON: ids and values, not objects", follows=_json_args
        ),
        Step("Service", "The task only calls it", follows=_uses_service),
        Step(
            "Result",
            "Kept by the result backend and task history",
            follows=_json_result,
        ),
    ),
    rules=(
        Rule(
            "json-args",
            "JSON arguments",
            "Arguments cross the broker as JSON. Pass ids and plain values and "
            "load the rest inside the task, where the data is current; every "
            "argument annotated so the check can tell.",
            _json_args,
        ),
        Rule(
            "thin",
            "Thin task",
            "The task unpacks its arguments and hands them to a service, so the "
            "same work can run from a route or a job: at most "
            f"{THIN_STATEMENTS} statements around a service call, or one statement.",
            lambda t: thin(t.func, _uses_service(t)),
        ),
        Rule(
            "json-result",
            "JSON result",
            "The result backend and the task history store what a task returns; "
            "a dict of plain values reads back anywhere.",
            _json_result,
        ),
    ),
    discover=tasks,
    function=lambda t: t.func,
    rank=_rank,
)
