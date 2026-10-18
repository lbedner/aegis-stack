"""The system model's parts: every installed component and service, the
sub-services in them (``ai.voice``, and a folder part of one: ``ai.rag``),
the app's shared code (``system``) and the worker's queue, inside the cache.
Each with its concern, its package's first docstring line and its other
names; ``ownership`` says which part owns any file."""

from collections.abc import Iterable, Mapping
from functools import cache
from typing import Any

import yaml

from app.core import ownership, source_index
from app.core.ontology.model import Kind, PartNode, PartOption, node_id
from app.core.parts import PARTS, Category, Part
from app.core.source_index import ROOT

# The worker's queue and where it lives: not a process of its own, so in
# the model a part of the one holding it, and on the map with the data,
# after the database.
QUEUE, QUEUE_IN = "queue", "cache"
QUEUE_PART = Part(
    kind="component",
    category=Category.DATA,
    cli="",
    tier=2,
    role="queue",
    order=45,
    description="The worker's queue, kept in the cache's Redis: while Redis is "
    "down no work is handed off or picked up.",
)
# Every part with a place on the map: each declared one, and the queue.
PLACED = {**PARTS, QUEUE: QUEUE_PART}
# What lives inside another part, so fails with it.
INSIDE = {QUEUE: QUEUE_IN}


def placement(name: str) -> tuple[bool, int, str]:
    """Where a part goes among others, in the sidebar and in its map row:
    by its declared ``order``, those with none after the rest, by name."""
    part = PLACED.get(name)
    order = part.order if part else None
    return (order is None, order or 0, name)


def on_disk(kind: Kind) -> list[str]:
    """The parts of ``kind`` this stack has, by the path only a stack with
    one has (``Part.marker``; none: every stack): what is there whether or
    not a health check registered it."""
    return [
        name
        for name, part in PARTS.items()
        if part.kind == kind.value
        and (not part.marker or (ROOT / part.marker).exists())
    ]


class _Packages:
    """Where each part's code is: its folder (by its own name or its CLI
    name), else the core client that fronts it. One lookup a build."""

    def __init__(self, index: source_index.Index) -> None:
        self.index = index
        self.fronted = {
            found.declared.fronts: module
            for module in index.paths
            if module.startswith("app.core.")
            and (found := index.get(module)) is not None
            and found.declared.fronts
        }

    def of(self, kind: Kind, name: str) -> source_index.Module | None:
        group = "components" if kind is Kind.COMPONENT else "services"
        for folder in ownership.folders(name):
            if f"app.{group}.{folder}" in self.index:
                return self.index.get(f"app.{group}.{folder}")
        module = self.fronted.get(name)
        return self.index.get(module) if module else None


def concern(name: str, package: source_index.Module | None) -> Category:
    """A part's concern: what its spec declares (``PLACED``: each part's,
    and the queue's), else what its package says (a plugin's
    ``CATEGORY``), else the app's own."""
    if name in PLACED:
        return PLACED[name].category
    declared = package.declared.category if package else None
    return Category(declared) if declared in Category else Category.APP


@cache
def concern_of(kind: Kind, name: str) -> Category:
    """``concern`` by name, its package found in the project's source."""
    return concern(name, _packages(source_index.project()).of(kind, name))


@cache
def _packages(index: source_index.Index) -> _Packages:
    return _Packages(index)


def _part(
    kind: Kind,
    name: str,
    package: source_index.Module | None,
    parent: PartNode | None = None,
) -> PartNode:
    if parent is not None:
        category = parent.category
    elif kind is Kind.SHARED:
        category = Category.STACK
    else:
        category = concern(name, package)
    return PartNode(
        kind=kind,
        name=name,
        owner=parent.id if parent else None,
        category=category,
        description=(package.summary if package else "")
        or (PLACED[name].description if name in PLACED else ""),
        cli=PARTS[name].cli if name in PARTS else None,
        page=ownership.COMPONENT_PAGES.get(name),
        options=options_of(name, answers()) if parent is None else (),
    )


@cache
def answers() -> dict[str, Any]:
    """What this stack was generated with (``.copier-answers.yml``); empty
    where the file is gone."""
    file = ROOT / ".copier-answers.yml"
    return (yaml.safe_load(file.read_text()) or {}) if file.is_file() else {}


def options_of(name: str, given: Mapping[str, Any]) -> tuple[PartOption, ...]:
    """What part ``name`` could be (``app/core/parts.py``), each option with
    the choice ``given`` (the stack's answers) records."""
    part = PARTS.get(name)
    return tuple(
        PartOption(
            name=o.name,
            mode=o.mode,
            choices=o.choices,
            default=bool(o.default) if o.mode == "flag" else o.default,
            chosen=_chosen(o.mode, given.get(o.answer)) if o.answer else None,
            ordered=o.ordered,
            about=dict(o.about),
        )
        for o in (part.options if part else ())
    )


def _chosen(mode: str, value: Any) -> str | tuple[str, ...] | bool | None:
    if value is None:
        return None
    if mode == "flag":
        return bool(value)
    if mode == "multi":
        held = value if isinstance(value, list) else str(value).split(",")
        return tuple(v.strip() for v in held if str(v).strip())
    return str(value)


def parts(
    components: Iterable[str], services: Iterable[str], index: source_index.Index
) -> list[PartNode]:
    """Every part: ``components`` and ``services`` (health names), their
    sub-services, the queue with a worker, and the app's shared code."""
    packages = _Packages(index)
    nodes = [
        _part(Kind.COMPONENT, n, packages.of(Kind.COMPONENT, n)) for n in components
    ]
    if "worker" in components:
        holder = next((n for n in nodes if n.name == QUEUE_IN), None)
        nodes.append(_part(Kind.COMPONENT, QUEUE, None, holder))
    for name in services:
        service = _part(Kind.SERVICE, name, packages.of(Kind.SERVICE, name))
        nodes += [service, *_subs(service, index)]
    return nodes + _folders(nodes, index)


def _subs(service: PartNode, index: source_index.Index) -> list[PartNode]:
    """A service's domains (``ai/domains/voice``): its sub-services."""
    prefix = f"app.services.{service.name}.domains."
    return [
        _part(
            Kind.SERVICE,
            f"{service.name}.{module.removeprefix(prefix)}",
            index.get(module),
            service,
        )
        for module in sorted(index.paths)
        if module.startswith(prefix) and "." not in module.removeprefix(prefix)
    ]


def _folders(nodes: list[PartNode], index: source_index.Index) -> list[PartNode]:
    """The services folders that are no service: a sub-service of the one
    they say they are part of (rag in AI), or the app's shared code."""
    by_id = {n.id: n for n in nodes}
    found = []
    for module in sorted(index.paths):
        folder = module.removeprefix("app.services.")
        if not module.startswith("app.services.") or "." in folder:
            continue
        owner = ownership.owner(module, index)
        if owner is None:
            continue
        if owner.kind == ownership.SHARED:
            found.append(_part(Kind.SHARED, folder, index.get(module)))
        elif owner.kind == ownership.SERVICE and owner.sub == folder:
            parent = by_id.get(node_id(Kind.SERVICE, owner.name))
            if parent is not None:
                name = f"{owner.name}.{folder}"
                found.append(_part(Kind.SERVICE, name, index.get(module), parent))
    return found


def owner_id(owner: ownership.Owner | None, ids: set[str] | None) -> str | None:
    """A file's owner as a node's id: its sub-service where that is one (of
    ``ids``, given them)."""
    if owner is None:
        return None
    base = node_id(Kind(owner.kind), owner.name)
    sub = f"{base}.{owner.sub}" if owner.sub else None
    if ids is None:
        return sub or base
    return sub if sub in ids else base if base in ids else None


def node_of(module: str, index: source_index.Index, ids: set[str] | None) -> str | None:
    """The node (of ``ids``, given them) owning ``module``, by
    ``ownership``'s rule."""
    return owner_id(ownership.owner(module, index), ids)


def service_folders(index: source_index.Index, ids: set[str]) -> list[tuple[str, str]]:
    """Each services folder that is a node's code, with that node's id:
    ``("rag", "service:ai.rag")``, ``("system", "shared:system")``."""
    return [
        (folder, found)
        for folder in index.packages_in("app.services")
        if (found := node_of(f"app.services.{folder}", index, ids))
    ]
