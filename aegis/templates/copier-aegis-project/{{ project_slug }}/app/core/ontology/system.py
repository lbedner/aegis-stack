"""``system_model``: what this app is, built from what is already there:
the health registry (what is installed), ``app.routes``, the scheduled
jobs, the worker's queues and tasks, the tool and change-type
registries, docker-compose's services, the map's component links
(``topology``), what each service's code and needed keys reach
(``calls``) and the tables (``domain``). Who owns each is
``ownership``'s one rule.

Whole only in the webserver, where startup registers every health check
and the routes are; anywhere else the model is what is on disk, marked
``partial``. Readers ask ``current``: built once, kept once whole."""

import asyncio
from collections.abc import Callable, Iterable
from functools import cache
import inspect
import threading
from typing import Any

from starlette.applications import Starlette
from starlette.routing import Route
import yaml

from app.core import ownership, runtime, secrets, source_index
from app.core.concurrency import background
from app.core.constants import ComponentName, QueueName
from app.core.ontology import calls, domain
from app.core.ontology.model import (
    ChangeNode,
    ContainerNode,
    Edge,
    EdgeKind,
    ExternalNode,
    JobNode,
    KeysNode,
    Kind,
    Mode,
    Node,
    PartNode,
    QueueNode,
    RouteNode,
    SystemModel,
    TaskNode,
    ToolNode,
    node_id,
    parse_node_id,
    stack,
)
from app.core.ontology.parts import QUEUE, node_of, on_disk, parts, service_folders
from app.core.parts import PARTS

COMPOSE = source_index.ROOT / "docker-compose.yml"
QUEUE_TYPE = "WORKER_QUEUE_TYPE"  # the queue a worker's container takes
QUEUE_ID = node_id(Kind.COMPONENT, QUEUE)
WORKER = ComponentName.WORKER
# Where code is: the part it belongs to and the module defining it.
Placed = Callable[[Callable[..., Any]], dict[str, str | None]]


_kept: SystemModel | None = None
_building = threading.Lock()


def current() -> SystemModel:
    """The model readers (the MCP tool, the API) ask for, built once: a
    partial one again only once health checks have registered since (the
    webserver's startup), else it is all this process will ever see."""
    global _kept
    with _building:  # two first asks (threads) build it once
        if _kept is None or (_kept.partial and _registered()):
            _kept = system_model()
    return _kept


async def warm() -> None:
    """Build the model now, off the loop, without waiting: the first to ask
    (``current``) gets this build. The webserver runs it once its parts
    have registered, a worker queue as it starts."""
    background(_build())


async def _build() -> None:
    await asyncio.to_thread(current)


def _registered() -> bool:
    from app.services.system import health

    names = health.registered_health_names()
    return bool(names["components"] or names["services"])


def with_app() -> SystemModel:
    """The model built with the whole app, its routes in it: what a process
    with no running backend (the CLI, a docs build) reads. Kept as
    ``current``'s, so the readers it serves (the ``ontology`` tool, asked
    from a shell) read it too."""
    global _kept
    from app.integrations.main import create_integrated_app

    with _building:
        _kept = system_model(create_integrated_app())
    return _kept


def system_model(app: Starlette | None = None) -> SystemModel:
    """The model, built now; ``app``'s routes in it (the running backend's
    when not given, none where there is no backend: the CLI)."""
    from app.components.backend.main import get_configured_app
    from app.services.system import health  # the registry startup fills

    app = app or get_configured_app()

    names = health.registered_health_names()
    partial = not _registered()
    index = source_index.project()
    # What is on disk joins what registered: a part with no health check
    # (deploy, the Flet frontend) is there all the same.
    components = [*dict.fromkeys([*names["components"], *on_disk(Kind.COMPONENT)])]
    services = list(names["services"]) or on_disk(Kind.SERVICE)
    found = parts(components, services, index)
    ids = {n.id for n in found}

    @cache
    def by_module(module: str) -> str | None:
        return node_of(module, index, ids)

    def placed(func: Callable[..., Any]) -> dict[str, str | None]:
        module = where(func)
        return {"owner": by_module(module), "module": module}

    containers = _containers()
    boxes = [c.name for c in containers]
    taking = {c.queue: c.name for c in containers if c.queue}
    jobs, own_jobs = _jobs(placed), _scheduler_jobs(placed)
    queues, tasks = _worker(placed, ids)
    changes = _changes(placed)
    tables, links = _tables(by_module)
    nodes: list[Node] = [
        *found,
        *containers,
        *_externals(),
        *(_routes(app, placed) if app else []),
        *_tools(placed),
        *changes,
        *jobs,
        *own_jobs,
        *queues,
        *tasks,
        *tables,
        *_keys(by_module, ids),
    ]
    every = {n.id for n in nodes}
    # A task is taken from the queue: its queue module's broker is not a
    # call it makes.
    taken = every - {QUEUE_ID}
    edges = [
        *_component_edges(found),
        *_contains(nodes),
        *_calls(every, index),
        *_code_calls([*jobs, *own_jobs], every, index),
        *_code_calls(tasks, taken, index),
        *_runs_on(found, jobs, own_jobs, boxes, taking),
        *_queued(queues, tasks, taking),
        *links,
        *domain.changing(changes),
    ]
    return SystemModel(
        partial=partial,
        stack=stack(),
        nodes=tuple(nodes),
        edges=tuple(dict.fromkeys(map(_moded, edges))),
    )


def where(func: Callable[..., Any]) -> str:
    """The module defining ``func``, through any wrapper."""
    return inspect.unwrap(func).__module__


def _moded(edge: Edge) -> Edge:
    """``edge`` asynchronous when it hands work to the queue or takes it
    from it (``topology.queued``), or hands it to a worker's task: never
    waited on. Containing it is not."""
    from app.services.system import topology

    (_, source), (kind, target) = map(parse_node_id, (edge.source, edge.target))
    queued = topology.queued(source, target) or kind is Kind.TASK
    if edge.kind is EdgeKind.CONTAINS or not queued:
        return edge
    return edge.model_copy(update={"mode": Mode.ASYNC})


def _routes(app: Starlette, placed: Placed) -> list[RouteNode]:
    """Every route the app answers, the ones left out of its OpenAPI schema
    (pages, docs) too: ``patterns.routes`` reads only the schema's."""
    found = {
        f"{method} {route.path}": RouteNode(
            name=f"{method} {route.path}",
            method=method,
            path=route.path,
            **placed(route.endpoint),
        )
        for route in app.routes
        if isinstance(route, Route)
        for method in sorted(route.methods or ())
    }
    return list(found.values())


def _schedule(trigger: dict[str, Any]) -> str:
    """A trigger as written: ``trigger=cron hour=3``."""
    return " ".join(f"{k}={v}" for k, v in trigger.items())


def _jobs(placed: Placed) -> list[JobNode]:
    from app.core.schedule import service_jobs

    return [
        JobNode(name=job.id, schedule=_schedule(job.trigger), **placed(job.func))
        for job in service_jobs()
    ]


def _scheduler_jobs(placed: Placed) -> list[JobNode]:
    """The scheduler's own (its heartbeat), beside the services'."""
    try:
        from app.components.scheduler import heartbeat
    except ImportError:  # no scheduler in this stack
        return []
    return [
        JobNode(
            name=heartbeat.HEARTBEAT_JOB_ID,
            schedule=_schedule(heartbeat.HEARTBEAT_TRIGGER),
            **placed(heartbeat.touch_scheduler_heartbeat),
        )
    ]


def _worker(placed: Placed, ids: set[str]) -> tuple[list[QueueNode], list[TaskNode]]:
    """Each of the worker's queues, in the cache's queue (the worker's own
    where there is none), and every task each registers
    (``patterns.tasks``: each engine's task object unwrapped to its
    function), on its queue."""
    try:
        from app.components.worker import patterns, registry
        from app.components.worker.queue_discovery import QUEUES_PACKAGE
    except ImportError:  # no worker in this stack
        return [], []
    owner = QUEUE_ID if QUEUE_ID in ids else node_id(Kind.COMPONENT, WORKER)
    queues = [
        QueueNode(name=name, owner=owner, module=f"{QUEUES_PACKAGE}.{name}")
        for name in registry.discover_worker_queues()
    ]
    tasks = [
        TaskNode(name=task.name, queue=task.queue, **placed(task.func))
        for _, task in patterns.tasks()
    ]
    return queues, tasks


def _keys(owned: Callable[[str], str | None], ids: set[str]) -> list[KeysNode]:
    """What each part keeps in Redis (``redis_keys``): held by the part
    declaring it, else by Redis (core's); none without Redis."""
    redis = node_id(Kind.COMPONENT, ComponentName.CACHE)
    if redis not in ids:
        return []
    from app.services.system import redis_keys

    return [
        KeysNode(
            name=family.pattern,
            title=family.name,
            purpose=family.purpose,
            type=family.kind,
            db=family.db,
            owner=owned(module) or redis,
            module=module,
        )
        for module, family in redis_keys.declared()
    ]


def _tools(placed: Placed) -> list[ToolNode]:
    from app.core import tools

    tools.load_tools()
    found = [tools.get_tool(name) for name in tools.registered_tool_names()]
    return [
        ToolNode(
            name=tool.name,
            effect=tool.effect,
            admin=tool.admin,
            **placed(tool.func),
        )
        for tool in found
        if tool is not None
    ]


def _changes(placed: Placed) -> list[ChangeNode]:
    try:
        from app.services.change_queue import registry
    except ImportError:  # no change queue in this stack
        return []
    registry.load_change_types()
    return [
        domain.change(name, executor, **placed(executor.execute))
        for name in registry.registered_change_types()
        if (executor := registry.executor_for(name))
    ]


def _tables(owned: Callable[[str], str | None]) -> tuple[list[Node], list[Edge]]:
    """Every table and its links (``domain``); none without a database."""
    try:
        from sqlmodel import SQLModel

        from app.core.model_registry import import_all_models
    except ImportError:  # no database in this stack
        return [], []
    import_all_models()  # every table, whoever imported what so far
    objects, links = domain.objects(SQLModel.metadata, owned)
    return [*objects, *domain.unmodeled(owned)], links


def _containers() -> list[ContainerNode]:
    """docker-compose's services, as it declares them (what runs now is
    the runtime's, ON-07): a worker's with the queue it takes. None
    without a compose file."""
    if not COMPOSE.is_file():
        return []
    services = (yaml.safe_load(COMPOSE.read_text()) or {}).get("services") or {}
    return [
        ContainerNode(name=name, image=spec.get("image"), queue=_takes(spec))
        if isinstance(spec, dict)
        else ContainerNode(name=name)
        for name, spec in services.items()
    ]


def _takes(spec: dict[str, Any]) -> str | None:
    """The queue a compose service's worker takes (``WORKER_QUEUE_TYPE``),
    its environment a list or a mapping; None for any other service."""
    env = spec.get("environment") or {}
    if isinstance(env, list):
        env = dict(item.partition("=")[::2] for item in env)
    return env.get(QUEUE_TYPE)


def _externals() -> list[ExternalNode]:
    """Each outside provider a service's needed keys are for, as of now."""
    return [
        ExternalNode(name=provider, keys=tuple(names))
        for provider, names in calls.provider_keys().items()
    ]


def _component_edges(found: Iterable[PartNode]) -> list[Edge]:
    """The map's lines between the processes and stores (``topology``)."""
    from app.services.system import topology

    components = [p.name for p in found if p.kind is Kind.COMPONENT]
    return [
        Edge(
            source=node_id(Kind.COMPONENT, a),
            target=node_id(Kind.COMPONENT, b),
            kind=EdgeKind.DEPENDS_ON,
        )
        for a, b in topology.shape(components).links
    ]


def _contains(nodes: Iterable[Node]) -> list[Edge]:
    """Each node in the part it belongs to: a sub-service in its service,
    the queue in the cache, a route, job, queue, task or tool in its
    owner."""
    return [
        Edge(source=p.owner, target=p.id, kind=EdgeKind.CONTAINS)
        for p in nodes
        if p.owner is not None
    ]


def _calls(ids: set[str], index: source_index.Index) -> list[Edge]:
    """What each services folder's code reaches (``calls``), from the part
    the folder is (rag's from ``service:ai.rag``); the app's shared code
    (what every service imports to be one) reaches nothing."""
    declared = secrets.declared()
    edges = []
    for folder, source in service_folders(index, ids):
        if parse_node_id(source)[0] is Kind.SHARED:
            continue
        package = index.root / "app" / "services" / folder
        edges += [
            Edge(source=source, target=target, kind=EdgeKind.CALLS)
            for target in calls.talks_to(package, declared, index)
            if target in ids and target != source
        ]
    return edges


def _code_calls(
    code: Iterable[JobNode | TaskNode], ids: set[str], index: source_index.Index
) -> list[Edge]:
    """What each job's or task's code reaches (``calls``): the backup job,
    the database."""
    return [
        Edge(source=node.id, target=target, kind=EdgeKind.CALLS)
        for node in code
        if node.module
        for target in calls.reaches(node.module, index)
        if target in ids and target != node.owner
    ]


def _queued(
    queues: list[QueueNode], tasks: list[TaskNode], taking: dict[str, str]
) -> list[Edge]:
    """Each queue handing its work to its tasks, both in the container
    taking that queue (``taking``); and a scheduled job, which the
    scheduler hands to the worker as the task named after its function,
    to that task."""
    from app.core.schedule import service_jobs

    by_name = {task.name: task.id for task in tasks}
    handed = [
        (node_id(Kind.JOB, job.id), by_name[job.task_name])
        for job in service_jobs()
        if job.task_name in by_name
    ] + [(node_id(Kind.QUEUE, task.queue), task.id) for task in tasks]
    placed = [(q.id, q.name) for q in queues] + [(t.id, t.queue) for t in tasks]
    run = [
        (code, node_id(Kind.CONTAINER, taking[queue]))
        for code, queue in placed
        if queue in taking
    ]
    return [Edge(source=a, target=b, kind=EdgeKind.CALLS) for a, b in handed] + [
        Edge(source=a, target=b, kind=EdgeKind.RUNS_ON, mode=Mode.ASYNC) for a, b in run
    ]


def _containers_of(part: PartNode, containers: list[str]) -> list[str]:
    """The compose services a component runs as: the ones its spec adds
    (``Part.containers``), the ones its Overseer page shows
    (``runtime.page_for``: ``webserver`` the backend's), or a plugin's of
    its own name."""
    own = set(PARTS[part.name].containers) if part.name in PARTS else set()
    page = ownership.page_of_part(part.name)
    return [
        c
        for c in containers
        if c in own or runtime.page_for(c) == page or c.replace("-", "_") == part.name
    ]


def _runs_on(
    found: Iterable[PartNode],
    jobs: Iterable[JobNode],
    own_jobs: Iterable[JobNode],
    containers: list[str],
    taking: dict[str, str],
) -> list[Edge]:
    """Where each part runs: a component in its containers; a service, the
    app's shared code or a component with none of its own in the host's
    (``ownership.HOST``); a sub-part with its part. A service's job runs on
    the worker's system queue where there is one, else in the scheduler;
    the scheduler's own, in the scheduler."""

    top = [p for p in found if p.owner is None]
    host_id = node_id(Kind.COMPONENT, ownership.HOST)
    host = next((p for p in top if p.id == host_id), None)
    hosted = _containers_of(host, containers) if host else []
    places = {
        p.id: (_containers_of(p, containers) if p.kind is Kind.COMPONENT else [])
        or hosted
        for p in top
    }
    worker = places.get(node_id(Kind.COMPONENT, WORKER), [])
    scheduler = places.get(node_id(Kind.COMPONENT, ComponentName.SCHEDULER), [])
    runner = [c for c in worker if c == taking.get(QueueName.SYSTEM)] or scheduler
    return [
        Edge(source=source, target=node_id(Kind.CONTAINER, c), kind=EdgeKind.RUNS_ON)
        for source, targets in places.items()
        for c in targets
    ] + [
        Edge(
            source=job.id,
            target=node_id(Kind.CONTAINER, c),
            kind=EdgeKind.RUNS_ON,
            mode=Mode.ASYNC,
        )
        for job, targets in [
            *((job, runner) for job in jobs),
            *((job, scheduler) for job in own_jobs),
        ]
        for c in targets
    ]
