"""Overseer's reads as tools (``app.core.tools.load_tools``): what is wrong
now (``health``), what broke (``errors``), what led up to it (``logs``),
what a request did (``requests``), what the app is (``ontology``) and what
it holds (``query`` over its database, ``storage`` over its buckets), for
an agent or an MCP client. The same reads Overseer's pages make, so a tool
and a page never disagree. Read-only."""

import asyncio
from collections import Counter
import importlib.util
from typing import Any

from starlette.datastructures import QueryParams

from app.core import replays, runtime
from app.core import storage as storage_seam
from app.core.audit import audit_emitter
from app.core.ontology import Kind, PartNode, graph
from app.core.ontology.model import Node, SystemModel
from app.core.ontology.observed import running
from app.core.ontology.summary import summary
from app.core.tools import current_agent_slug, register_tool
from app.services.shared.deps import caller_is_admin
from app.services.system import (
    dry_path,
    kept_requests,
    live_status,
    pattern_findings,
    plugin_directory,
    service_parts,
    ui_errors,
    ui_logs,
)
from app.services.system import aggregate_reads  # noqa: F401 - registers ``aggregate``
from app.services.system.models import ComponentStatus
from app.services.system.node_now import (
    attention,
    check_of,
    checks,
    containers_now,
    now_of,
)
from app.services.system.tool_models import (
    AppSummary,
    BriefNode,
    BucketLevel,
    Buckets,
    ComponentHealth,
    HealthNow,
    HealthTree,
    Issue,
    Issues,
    LogEntry,
    Logs,
    Matches,
    NodeAnswer,
    NodeAnswers,
    OneRequest,
    Paths,
    QueryRows,
    RecentRequests,
    RouteWalk,
    Walk,
)

# The most log lines one call returns, newest first.
MAX_LINES = 500
# The most a listing tool returns (an ``ontology`` call's nodes and edges,
# requests, plugins, a bucket's files); each says when there were more.
MAX_NODES = 100


def _tree(component: ComponentStatus) -> HealthTree:
    parts = component.sub_components
    return HealthTree(
        status=component.status.value,
        message=component.message,
        parts={name: _tree(part) for name, part in parts.items()} or None,
    )


def _names(components: dict[str, ComponentStatus]) -> list[str]:
    return [
        name
        for key, component in components.items()
        for name in (key, *_names(component.sub_components))
    ]


async def health(component: str | None = None) -> HealthNow | ComponentHealth:
    """The app's health right now: every component (server, worker,
    scheduler, database, redis, ...) and service, each with its status
    (healthy, info, warning, unhealthy) and message, nested as Overseer
    shows them. ``component`` narrows it to one, with the details it
    reports that fit here (a worker's queues, the scheduler's jobs, the
    database's size and counts); ``omitted`` names those only Overseer
    shows; and ``containers``, what each container behind it uses
    (memory in MB against its limit, CPU, restarts). ``counts`` counts each check once, and ``attention`` names
    every one not healthy, with its message. Start here, then read what
    broke with ``errors`` and what led up to it with ``logs``. A part's
    ontology id (``service:documents``) names its check too."""
    if component is None:
        status, note = await live_status.live_status()
        found = list(checks(status.components))
        return HealthNow(
            healthy=status.overall_healthy,
            checked_at=status.timestamp,
            counts=Counter(c.status.value for _, c in found),
            attention=list(attention(status.components)),
            components={
                name: _tree(part) for name, part in status.components.items()
            },
            note=note,
        )
    # An ontology id (``component:worker``) names the same check.
    (status, note), (boxes, boxes_note) = await asyncio.gather(
        live_status.live_status(), containers_now(component.rpartition(":")[2])
    )
    found = check_of(status.components, component)
    if found is None:
        known = ", ".join(_names(status.components))
        raise ValueError(f"No component {component!r}; known: {known}")
    return ComponentHealth(
        component=found, containers=list(boxes), containers_note=boxes_note, note=note
    )


async def errors(
    text: str | None = None,
    service: str | None = None,
    level: str | None = None,
    window_seconds: int | None = None,
    issue: str | None = None,
) -> Issues | Issue:
    """Errors the app's containers logged, grouped into issues by where
    they come from, latest first (the first 25): each with its message,
    exception type, how often and when it first and last happened.
    ``text`` matches the message or exception type, ``service`` is an
    Overseer page (server, worker, scheduler, ...), ``level`` is error or
    critical, ``window_seconds`` how far back. ``issue`` (an issue's
    ``fingerprint``) reads that one instead: its latest occurrence with
    the full traceback, and its occurrences."""
    if issue:
        found = await ui_errors.load({"issue": issue}, ui_errors.load_detail)
        return Issue(
            detail=found["error_detail"],
            occurrences=found["error_history"],
            total=found["error_history_total"],
            note=found["error_note"],
        )
    query = {
        "q": text,
        "service": service,
        "level": level,
        "window": str(window_seconds) if window_seconds else None,
    }
    found = await ui_errors.load({k: v for k, v in query.items() if v})
    return Issues(
        issues=found["error_rows"], total=found["error_total"], note=found["error_note"]
    )


async def logs(
    service: str | None = None,
    level: str | None = None,
    text: str | None = None,
    window_seconds: int = ui_logs.DEFAULT_WINDOW,
    limit: int = 200,
) -> Logs:
    """The app's container logs, newest first, a traceback folded into the
    line it belongs to. ``service`` is an Overseer page (server, worker,
    scheduler, database, redis, ...; every one when omitted), ``level``
    keeps that level and worse (debug, info, warning, error, critical),
    ``text`` matches the line or its traceback. ``window_seconds`` is how
    far back: 900, 3600, 21600 or 86400, or 0 for each container's whole
    log. ``limit`` caps the lines (at most 500)."""
    pages = sorted(runtime.PAGES)
    if service is not None:
        if service not in runtime.PAGES:
            raise ValueError(f"No service {service!r}; known: {', '.join(pages)}")
        pages = [service]
    levels: list[str] = list(ui_logs.LEVELS)
    picked = levels[levels.index(level) :] if level in levels else []
    query = QueryParams(
        [("q", text or ""), ("window", str(window_seconds))]
        + [("level", name) for name in picked]
    )
    found = await ui_logs.recent(pages, query)
    return Logs(
        lines=[_line(row) for row in found["lines"][: min(limit, MAX_LINES)]],
        note=found["note"],
    )


def _line(row: dict[str, Any]) -> LogEntry:
    return LogEntry(
        at=row["at"],
        service=row["page"],
        container=row["instance"],
        level=row["level"],
        message=row["message"],
        logger=row["logger"],
        fields=dict(row["fields"]),
        trace=row["trace"],
    )


async def requests(
    request_id: str | None = None, route: str | None = None
) -> RecentRequests | OneRequest:
    """The requests the server answered, as it ran them: the latest
    hundred, newest first (``kept`` says how many it keeps), each with its route,
    status, length and hop count; ``route`` (as declared,
    ``/api/v1/users/{id}``) keeps one route's. ``request_id`` (a
    request's ``id``, or the ``X-Request-Id`` an answer carries) reads
    one with its hops in the order they started: what each went through
    (``chain``, model node ids, as ``ontology``'s dry path names them),
    when it started and how long it took (real milliseconds), whether it
    failed, the tables a query touched and the lines of code it was made
    through, each with the service and piece it is in. The server's last
    requests, kept a day."""
    if request_id is None:
        found = await kept_requests.recent(route, MAX_NODES)
        return RecentRequests(requests=found, kept=replays.KEEP)
    one = await kept_requests.find(request_id)
    if one is None:
        raise ValueError(f"No request {request_id!r} kept; list them with no id.")
    return OneRequest(request=one)


async def _dry_path(route: str) -> RouteWalk:
    if not await caller_is_admin():
        raise ValueError("A route's dry path is its code: an admin's to read.")
    walked = await dry_path.of(route)
    return RouteWalk(
        dry_path=Walk.model_validate({**dict(walked), "hops": walked.hops[:MAX_NODES]}),
        total={"hops": len(walked.hops)},
    )


def _findings(node: Node) -> list[pattern_findings.Finding]:
    """What the parts pattern finds in a part's code, as the map shows it
    (read from source once a process, so off the event loop)."""
    if not isinstance(node, PartNode):
        return []
    report = service_parts.report()
    return [f for f in pattern_findings.findings(report) if f.subject == node.id]


async def _node(
    model: SystemModel, node_id: str, depth: int, note: str | None
) -> NodeAnswer:
    """One node's answer (``ontology``'s ``node``)."""
    here, near, edges = graph.neighbors(model, node_id, depth)
    now, findings = await asyncio.gather(
        now_of(here), asyncio.to_thread(_findings, here)
    )
    return NodeAnswer(
        node=here,
        now=now,
        findings=findings,
        edges=edges[:MAX_NODES],
        neighbors=[BriefNode.of(n) for n in near[:MAX_NODES]],
        total={"edges": len(edges), "neighbors": len(near)},
        note=note,
    )


async def ontology(
    kind: str | None = None,
    category: str | None = None,
    text: str | None = None,
    node: str | list[str] | None = None,
    to: str | None = None,
    depth: int = 1,
    route: str | None = None,
) -> AppSummary | Matches | NodeAnswer | NodeAnswers | Paths | RouteWalk:
    """What this app is, read from its code: its tables and the changes to
    them (an admin also sees parts, routes, jobs, the worker's queues
    (``node="queue:<name>"``: its tasks, its container and its live
    state, in one call) and tasks, tools and Redis keys:
    ``kind="keys"``, every key family the app keeps there, what each holds
    and its type). No
    arguments: a summary (the app, counts by kind, its tables by owner with
    their links, the changes to them, and an admin's parts and scheduled
    jobs). ``kind``,
    ``category`` or ``text``: matching nodes. ``node`` (an id like
    ``object:user``): it, its edges and neighbours ``depth`` steps out,
    and for a part what is true of it now (its health check, the errors it
    owns, what each of its containers uses: memory in MB against its
    limit, CPU, restarts; the AI service's spend by window, and when they
    were read),
    what its code breaks of the service standard (``findings``: each
    rule, how bad, why, the file:line that shows it, what to do), and on
    the node what else it could be (``options``: each one's choices, the
    default, this stack's choice and what each choice means; ``chosen`` is
    what the stack was generated with, so the AI providers chosen are the
    ones installed, while the model in use is picked at runtime); a list
    of ids: each one's answer, in one call (``nodes``); with ``to``, the
    paths between the two. ``route`` (``GET /api/v1/...``,
    an admin's): every hop it can take, read from the code without sending
    it, each at its file and line, and where the walk stops. An edge's
    ``mode`` is whether the caller waits on it (``sync``) or hands it to
    the queue (``async``), not how either is written: only a hand-off
    carries one, every other call waits."""
    if route:
        return await _dry_path(route)
    model = await running()
    if not await caller_is_admin():
        model = model.domain()
    note = "Partial: built outside the webserver." if model.partial else None
    if isinstance(node, list):
        if to:
            raise ValueError("Paths run from one node: name one with `to`.")
        read = (_node(model, n, depth, note) for n in node)
        return NodeAnswers(nodes=list(await asyncio.gather(*read)))
    if node and to:
        return Paths(paths=graph.paths(model, node, to), note=note)
    if node:
        return await _node(model, node, depth, note)
    if kind is not None and kind not in set(Kind):
        raise ValueError(f"No kind {kind!r}; known: {', '.join(Kind)}")
    if kind or category or text:
        matches = [
            n
            for n in model.nodes
            if (kind is None or n.kind == kind)
            and (category is None or getattr(n, "category", None) == category)
            and (text is None or text.lower() in n.id.lower())
        ]
        listed = [BriefNode.of(n) for n in matches[:MAX_NODES]]
        return Matches(nodes=listed, total=len(matches), note=note)
    found = summary(model)
    # A reader who may not see parts (``domain``) is not told of them.
    named = {
        "parts": tuple(BriefNode.of(p, "category") for p in found.parts) or None,
        "jobs": tuple(BriefNode.of(j, "schedule") for j in found.jobs) or None,
    }
    return AppSummary.model_validate({**dict(found), **named, "note": note})


async def plugins(text: str | None = None) -> plugin_directory.PluginsAnswer:
    """The plugins this app has (each with its version and the options it
    was added with), and the ones it could add from the public directory
    at aegis-stack.io (``text`` matches a name or summary): what each is,
    its latest version, whether it is verified, the aegis it needs and the
    commands that add it, its downloads, stars, repository and release.
    The first hundred are listed and ``directory_total`` says how many
    match; ``text`` narrows them. Nothing is installed from here."""
    return await plugin_directory.plugins_now(text, limit=MAX_NODES)


async def query(sql: str) -> QueryRows:
    """One read-only SQL statement over the app's database, as Overseer's
    Database > Query runs it: count, group and join the app's tables
    (``SELECT kind, count(*) FROM job_execution GROUP BY kind``) rather
    than guess a figure. The first 200 rows (``more`` says there were
    more); a write is refused, a secret reads as hidden, a slow one is
    stopped. Each run is audited. Know a table's columns before you write
    the statement: ``ontology`` with ``node="object:<table>"`` lists them
    (``kind="object"`` lists the tables); never read a row to learn them,
    and never guess one."""
    from app.services.system import db_query, db_rows  # the database component's

    try:
        outcome, found = await asyncio.to_thread(db_query.attempt, sql)
    except db_rows.RowsHiddenError as exc:
        outcome, found = "refused", str(exc)
    await audit_emitter.emit(
        "database.query",
        actor_id=f"agent:{current_agent_slug.get() or 'tool'}",
        detail=sql,
        outcome=outcome,
    )
    if isinstance(found, str):
        raise ValueError(found)
    return QueryRows(columns=found.columns, rows=found.rows, more=found.more)


async def storage(bucket: str | None = None, prefix: str = "") -> Buckets | BucketLevel:
    """The app's object storage, as Overseer's Storage browses it: no
    ``bucket``, the buckets it can see; a ``bucket``, one level of it under
    ``prefix`` (``docs/``): its folders and its files (key, size, when
    modified), the first hundred. How the store is doing is the
    ``health`` tool's."""
    store: Any = storage_seam.get_storage()
    if not hasattr(store, "browse"):
        raise ValueError("Files are kept on the filesystem here, not in a bucket.")
    if bucket is None:
        return Buckets(buckets=[b["name"] for b in await store.buckets()])
    level = await store.browse(bucket, prefix, MAX_NODES)
    return BucketLevel(bucket=bucket, prefix=prefix, **level)


register_tool(
    "health",
    health,
    description="What is wrong now: every component's status and message",
    effect="read",
    doing="Checking what is wrong now",
    admin=True,
)
register_tool(
    "plugins",
    plugins,
    description="The plugins this app has, and the ones it could add",
    effect="read",
    doing="Looking at the plugins",
    admin=True,
)
register_tool(
    "errors",
    errors,
    description="What broke: retained errors grouped into issues, with tracebacks",
    effect="read",
    doing="Looking through the errors",
    admin=True,
)
register_tool(
    "requests",
    requests,
    description="What a request did: the recent ones, or one hop by hop",
    effect="read",
    doing="Following a request",
    admin=True,
)
register_tool(
    "logs",
    logs,
    description="What led up to it: container logs by service, level and text",
    effect="read",
    doing="Reading the logs",
    admin=True,
)
register_tool(
    "ontology",
    ontology,
    description=(
        "What the app is: its tables and the changes to them; for an admin "
        "also its parts, routes, jobs and tools, and how they connect"
    ),
    effect="read",
    doing="Looking up how the parts connect",
)
if importlib.util.find_spec("app.services.system.db_query"):
    register_tool(
        "query",
        query,
        description="What the database holds: one read-only SQL statement",
        effect="read",
        doing="Querying the database",
        admin=True,
    )
if importlib.util.find_spec("app.components.storage"):
    register_tool(
        "storage",
        storage,
        description="What the buckets hold: the buckets, or one level of one",
        effect="read",
        doing="Looking in the buckets",
        admin=True,
    )
