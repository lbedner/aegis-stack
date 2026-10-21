"""``system_model``: what this app is, built from what is already there:
the health registry (what is installed), ``app.routes``, the scheduled
jobs, the tool and change-type registries, docker-compose's services, the
map's component links (``topology``), what each service's code and
needed keys reach (``calls``) and the tables (``domain``). Who owns each
is ``ownership``'s one rule.

Whole only in the webserver, where startup registers every health check
and the routes are; anywhere else the model is what is on disk, marked
``partial``. Readers ask ``current``: built once, kept once whole."""

from collections.abc import Callable, Iterable
from functools import cache
import inspect
import threading
from typing import Any

from starlette.applications import Starlette
from starlette.routing import Route
import yaml

from app.core import ownership, runtime, secrets, source_index
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
    RouteNode,
    SystemModel,
    ToolNode,
    node_id,
    parse_node_id,
    stack,
)
from app.core.ontology.parts import node_of, on_disk, parts, service_folders
from app.core.parts import PARTS

COMPOSE = source_index.ROOT / "docker-compose.yml"
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


def _registered() -> bool:
    from app.services.system import health

    names = health.registered_health_names()
    return bool(names["components"] or names["services"])


def with_app() -> SystemModel:
    """The model built with the whole app, its routes in it: what a process
    with no running backend (the CLI, a docs build) reads."""
    from app.integrations.main import create_integrated_app

    return system_model(create_integrated_app())


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
    jobs, own_jobs = _jobs(placed), _scheduler_jobs(placed)
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
        *tables,
        *_keys(by_module, ids),
    ]
    edges = [
        *_component_edges(found),
        *_contains(nodes),
        *_calls({n.id for n in nodes}, index),
        *_job_calls([*jobs, *own_jobs], {n.id for n in nodes}, index),
        *_runs_on(found, jobs, own_jobs, [c.name for c in containers]),
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
    from it (``topology.queued``): never waited on. Containing it is not."""
    from app.services.system import topology

    queued = topology.queued(
        parse_node_id(edge.source)[1], parse_node_id(edge.target)[1]
    )
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
    the runtime's, ON-07). None without a compose file."""
    if not COMPOSE.is_file():
        return []
    services = (yaml.safe_load(COMPOSE.read_text()) or {}).get("services") or {}
    return [
        ContainerNode(
            name=name, image=spec.get("image") if isinstance(spec, dict) else None
        )
        for name, spec in services.items()
    ]


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
    the queue in the cache, a route, job or tool in its owner."""
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


def _job_calls(
    jobs: Iterable[JobNode], ids: set[str], index: source_index.Index
) -> list[Edge]:
    """What each job's code reaches (``calls``): the backup job, the
    database."""
    return [
        Edge(source=job.id, target=target, kind=EdgeKind.CALLS)
        for job in jobs
        if job.module
        for target in calls.reaches(job.module, index)
        if target in ids and target != job.owner
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
    worker = places.get(node_id(Kind.COMPONENT, "worker"), [])
    scheduler = places.get(node_id(Kind.COMPONENT, ComponentName.SCHEDULER), [])
    runner = [c for c in worker if c.endswith(QueueName.SYSTEM)] or scheduler
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
