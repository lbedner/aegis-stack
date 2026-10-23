"""Context for the Overseer Patterns page: how this app is built.

Backend patterns are detected in the running app: routes by
``app.services.system.patterns``, worker tasks (when the worker is
installed) by ``app.components.worker.patterns``. The frontend's are the
shared macros (``macro_catalog``). One page for a person or an agent to
read before building.
"""

import asyncio
from collections.abc import Sequence
import inspect
from typing import Any

from starlette.routing import BaseRoute

from app.core.ontology.model import parse_node_id
from app.core.parts import Category
from app.core.route_auth import route_requires_auth
from app.services.system import patterns, service_parts, ui_backend
from app.services.system.models import ComponentStatus

from . import macro_catalog
from . import overseer_conformance as conformance
from .overseer_nav import NavItem, SectionRequest
from .rendering import status_cell

PATTERNS = patterns.installed_patterns()
PATTERN = "pages/overseer/patterns/_pattern.html"
CATALOG = "pages/overseer/patterns/_catalog.html"

SECTIONS = (
    ("Backend", {key: p.title for key, p in PATTERNS.items()}),
    (
        "Frontend",
        {
            "layout": "Layout",
            "feedback": "Feedback",
            "form": "Forms",
            "table": "Tables",
        },
    ),
)

# The sidebar entry. No health check stands behind it, so no status.
ITEM = NavItem(
    group="patterns",
    name="patterns",
    title="Patterns",
    url="/overseer/patterns",
    status="",
    component=ComponentStatus(name="patterns", message=""),
    concern=Category.PLATFORM,
)


def _state(instance: patterns.Instance, titles: dict[str, str]) -> dict[str, Any]:
    count = len(instance.findings)
    return {
        "summary": ", ".join(titles[k] for k in instance.findings) or None,
        "state": status_cell(f"{count} finding{'s' * (count != 1)}", "warn")
        if count
        else status_cell("Follows", "ok"),
    }


def _route_row(instance: patterns.Instance) -> dict[str, Any]:
    route = instance.target
    return {
        "path": route.path,
        "methods": sorted(m for m in route.methods if m != "HEAD"),
        "tags": route.tags,
        "name": route.name,
        "dependencies": sorted(patterns.dependency_names(route) - {""}),
        "auth": status_cell("Auth", "warn") if route_requires_auth(route) else None,
    }


def _task_row(instance: patterns.Instance) -> dict[str, Any]:
    task = instance.target
    return {
        "group": task.queue,
        "name": task.name,
        "arguments": ", ".join(inspect.signature(task.func).parameters) or None,
        "statements": patterns.statement_count(task.func),
    }


def _function_row(instance: patterns.Instance) -> dict[str, Any]:
    """A function read from the source (a service's, an async one), grouped
    by the part it is in."""
    function = instance.target
    return {
        "group": function.group,
        "name": function.qualname,
        "file": function.path,
        "statements": function.statements,
    }


def _parts_row(instance: patterns.Instance) -> dict[str, Any]:
    """A services folder's parts: the ones it has and, for a service of
    its own, the ones it lacks. Grouped by what it is to the model."""
    kind, name = parse_node_id(instance.label)
    has = [label for label, found in instance.target.has.items() if found]
    return {
        "group": kind.value.title(),
        "name": name,
        "has": ", ".join(has) or None,
        "missing": ", ".join(instance.missed) or None,
    }


ROWS = {
    "route": _route_row,
    "task": _task_row,
    "service": _function_row,
    "parts": _parts_row,
    "async": _function_row,
}

_STATUS = [
    {"key": "state", "label": "Status", "kind": "status"},
    {"key": "summary", "label": "Findings"},
]
_STATEMENTS = {
    "key": "statements",
    "label": "Statements",
    "kind": "int",
    "align": "right",
}
_FUNCTIONS = [
    {"key": "name", "label": "Function"},
    {"key": "file", "label": "File"},
    _STATEMENTS,
    *_STATUS,
]
COLUMNS = {
    "task": [
        {"key": "name", "label": "Task"},
        {"key": "arguments", "label": "Arguments"},
        _STATEMENTS,
        *_STATUS,
    ],
    "service": _FUNCTIONS,
    "async": _FUNCTIONS,
    "parts": [
        {"key": "name", "label": "Part"},
        {"key": "has", "label": "Has"},
        {"key": "missing", "label": "Lacks"},
        *_STATUS,
    ],
}


def _groups(
    key: str, rows: list[dict[str, Any]]
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Routes by tag (the Server page's grouping); the rest by their group."""
    if key == "route":
        return ui_backend.route_groups(rows)
    names = sorted({row["group"] for row in rows})
    return [(n, [row for row in rows if row["group"] == n]) for n in names]


def pattern_view(report: patterns.Report) -> dict[str, Any]:
    """A report as the pattern template reads it."""
    pattern = report.pattern
    titles = {rule.key: rule.title for rule in pattern.rules}
    rows = [ROWS[pattern.key](i) | _state(i, titles) for i in report.instances]
    if pattern.key == service_parts.PARTS.key:  # as the map's hover lists them
        for row, instance in zip(rows, report.instances, strict=True):
            row["todo"] = conformance.part_todos(instance.label)
    canonical = None
    if report.canonical is not None:
        code, path = patterns.source(pattern.function(report.canonical.target))
        canonical = {"label": report.canonical.label, "code": code, "path": path}
    return {
        "pattern": pattern,
        "total": len(report.instances),
        "steps": report.steps,
        "rules": report.rules,
        "canonical": canonical,
        "route_groups": _groups(pattern.key, rows),
        "instance_columns": COLUMNS.get(pattern.key, []),
        "groups_open": False,
        "exemptions": pattern.exemptions,
    }


async def section_context(
    section: str, component: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """A backend pattern's report, or a macro file's catalog."""
    if section in macro_catalog.FILES:
        return {"macros": macro_catalog.catalog(section), "section_partial": CATALOG}
    view = await asyncio.to_thread(_pattern_view, section, req.routes)
    return view | {"section_partial": PATTERN}


# (section, id of the app's route list) -> (that list, its view). Routes
# and registered tasks only change when the code reloads, which restarts
# the process, so a report is built once per pattern per process.
_VIEWS: dict[tuple[str, int], tuple[Sequence[BaseRoute], dict[str, Any]]] = {}


def _pattern_view(section: str, routes: Sequence[BaseRoute]) -> dict[str, Any]:
    cached = _VIEWS.get((section, id(routes)))
    if cached is not None and cached[0] is routes:
        return cached[1]
    # The parts report reads the source, not the routes: one for the map too.
    report = (
        service_parts.report()
        if section == service_parts.PARTS.key
        else patterns.report(PATTERNS[section], routes)
    )
    view = pattern_view(report)
    _VIEWS[(section, id(routes))] = (routes, view)
    return view
