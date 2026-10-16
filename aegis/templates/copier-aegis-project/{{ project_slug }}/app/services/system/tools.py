"""Overseer's reads as tools (``app.core.tools.load_tools``): what is wrong
now (``health``), what broke (``errors``), what led up to it (``logs``)
and what the app is (``ontology``), for an agent or an MCP client. The
same reads Overseer's pages make, so a tool and a page never disagree.
Read-only."""

import asyncio
from collections import Counter
from collections.abc import Iterator
from typing import Any

from starlette.datastructures import QueryParams

from app.core import runtime
from app.core.ontology import Kind, graph
from app.core.ontology.observed import running
from app.core.ontology.summary import summary
from app.core.tools import register_tool
from app.services.shared.deps import caller_is_admin
from app.services.system import dry_path, live_status, ui_errors, ui_logs
from app.services.system.models import ComponentStatus

# The most log lines one call returns, newest first.
MAX_LINES = 500
# The most nodes (and edges) an ``ontology`` call lists; ``total`` says all.
MAX_NODES = 100
# What a node is, in a list.
BRIEF = {"id", "kind", "name", "owner"}


def _tree(component: ComponentStatus) -> dict[str, Any]:
    node: dict[str, Any] = {
        "status": component.status.value,
        "message": component.message,
    }
    if component.sub_components:
        node["parts"] = {
            name: _tree(part) for name, part in component.sub_components.items()
        }
    return node


def _checks(
    components: dict[str, ComponentStatus], prefix: str = ""
) -> Iterator[tuple[str, ComponentStatus]]:
    """Each check in the tree by its dotted name, but one only passing on
    its parts' issues (``aegis``, ``components``): it is not one more."""
    for key, component in components.items():
        name = f"{prefix}{key}"
        yield from _checks(component.sub_components, f"{name}.")
        parts = component.sub_components.values()
        if component.healthy or all(p.healthy for p in parts):
            yield name, component


def _find(components: dict[str, ComponentStatus], name: str) -> ComponentStatus | None:
    for key, component in components.items():
        if key == name:
            return component
        if found := _find(component.sub_components, name):
            return found
    return None


def _names(components: dict[str, ComponentStatus]) -> list[str]:
    return [
        name
        for key, component in components.items()
        for name in (key, *_names(component.sub_components))
    ]


async def health(component: str | None = None) -> dict[str, Any]:
    """The app's health right now: every component (server, worker,
    scheduler, database, redis, ...) and service, each with its status
    (healthy, info, warning, unhealthy) and message, nested as Overseer
    shows them. ``component`` narrows it to one, with everything it
    reports (a worker's queues, the scheduler's jobs, the database's
    tables). ``counts`` counts each check once, and ``attention`` names
    every one not healthy, with its message. Start here, then read what
    broke with ``errors`` and what led up to it with ``logs``."""
    status, note = await live_status.live_status()
    if component is None:
        checks = list(_checks(status.components))
        return {
            "healthy": status.overall_healthy,
            "checked_at": status.timestamp.isoformat(),
            "counts": Counter(c.status.value for _, c in checks),
            "attention": [
                {"name": name, "status": c.status.value, "message": c.message}
                for name, c in checks
                if not c.healthy
            ],
            "components": {
                name: _tree(part) for name, part in status.components.items()
            },
            "note": note,
        }
    found = _find(status.components, component)
    if found is None:
        known = ", ".join(_names(status.components))
        raise ValueError(f"No component {component!r}; known: {known}")
    return {"component": found.model_dump(mode="json"), "note": note}


async def errors(
    text: str | None = None,
    service: str | None = None,
    level: str | None = None,
    window_seconds: int | None = None,
    issue: str | None = None,
) -> dict[str, Any]:
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
        detail = found["error_detail"]
        return {
            "detail": detail.model_dump(mode="json") if detail else None,
            "occurrences": [o.model_dump(mode="json") for o in found["error_history"]],
            "total": found["error_history_total"],
            "note": found["error_note"],
        }
    query = {
        "q": text,
        "service": service,
        "level": level,
        "window": str(window_seconds) if window_seconds else None,
    }
    found = await ui_errors.load({k: v for k, v in query.items() if v})
    return {
        "issues": [row.model_dump(mode="json") for row in found["error_rows"]],
        "total": found["error_total"],
        "note": found["error_note"],
    }


async def logs(
    service: str | None = None,
    level: str | None = None,
    text: str | None = None,
    window_seconds: int = ui_logs.DEFAULT_WINDOW,
    limit: int = 200,
) -> dict[str, Any]:
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
    return {
        "lines": [_line(row) for row in found["lines"][: min(limit, MAX_LINES)]],
        "note": found["note"],
    }


def _line(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "at": row["at"],
        "service": row["page"],
        "container": row["instance"],
        "level": row["level"],
        "message": row["message"],
        "trace": row["trace"],
    }


async def _dry_path(route: str) -> dict[str, Any]:
    if not await caller_is_admin():
        raise ValueError("A route's dry path is its code: an admin's to read.")
    from app.components.backend.main import get_configured_app

    app = get_configured_app()
    found = dry_path.find(app.routes if app else [], route)
    if found is None:
        raise ValueError(f"No route {route!r}; name one as 'METHOD /path'.")
    walked = await asyncio.to_thread(dry_path.walk, found)
    return {
        "dry_path": walked.model_dump(mode="json", exclude={"hops"})
        | {"hops": [h.model_dump(mode="json") for h in walked.hops[:MAX_NODES]]},
        "total": {"hops": len(walked.hops)},
    }


async def ontology(
    kind: str | None = None,
    category: str | None = None,
    text: str | None = None,
    node: str | None = None,
    to: str | None = None,
    depth: int = 1,
    route: str | None = None,
) -> dict[str, Any]:
    """What this app is, read from its code: its tables and the changes to
    them (an admin also sees parts, routes, jobs, tools and Redis keys). No
    arguments: a summary (the app, counts by kind, its tables by owner with
    their links, the changes to them, and an admin's parts). ``kind``,
    ``category`` or ``text``: matching nodes. ``node`` (an id like
    ``object:user``): it, its edges and neighbours ``depth`` steps out;
    with ``to``, the paths between the two. ``route`` (``GET /api/v1/...``,
    an admin's): every hop it can take, read from the code without sending
    it, each at its file and line, and where the walk stops. An edge's
    ``mode`` is whether the caller waits on it (``sync``) or hands it to
    the queue (``async``), not how either is written."""
    if route:
        return await _dry_path(route)
    model = await running()
    if not await caller_is_admin():
        model = model.domain()
    note = "Partial: built outside the webserver." if model.partial else None
    if node and to:
        found = graph.paths(model, node, to)
        dumped = [[e.model_dump(mode="json") for e in path] for path in found]
        return {"paths": dumped, "note": note}
    if node:
        here, near, edges = graph.neighbors(model, node, depth)
        return {
            "node": here.model_dump(mode="json"),
            "edges": [e.model_dump(mode="json") for e in edges[:MAX_NODES]],
            "neighbors": [
                n.model_dump(mode="json", include=BRIEF) for n in near[:MAX_NODES]
            ],
            "total": {"edges": len(edges), "neighbors": len(near)},
            "note": note,
        }
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
        return {
            "nodes": [
                n.model_dump(mode="json", include=BRIEF) for n in matches[:MAX_NODES]
            ],
            "total": len(matches),
            "note": note,
        }
    found = summary(model)
    brief = found.model_dump(mode="json", exclude={"parts"}) | {"note": note}
    if not found.parts:  # the app's data alone (``domain``)
        return brief
    return brief | {
        "parts": [
            p.model_dump(mode="json", include={*BRIEF, "category"}) for p in found.parts
        ]
    }


register_tool(
    "health",
    health,
    description="What is wrong now: every component's status and message",
    effect="read",
    admin=True,
)
register_tool(
    "errors",
    errors,
    description="What broke: retained errors grouped into issues, with tracebacks",
    effect="read",
    admin=True,
)
register_tool(
    "logs",
    logs,
    description="What led up to it: container logs by service, level and text",
    effect="read",
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
)
