"""The system model in the formats other tools read (``ontology export``):
the docs' ``stack.md`` (``markdown``), Backstage's ``catalog-info.yaml``
(``backstage``), and the OpenTelemetry resource attributes each process
reports its traces under (``otel``). Pure functions of the model, so what
Aegis knows of the app is never locked inside Aegis."""

from collections import Counter
from typing import Any

import yaml

from app.core.ontology.model import (
    EdgeKind,
    ExternalNode,
    Kind,
    PartNode,
    Stack,
    SystemModel,
)
from app.core.parts import Category

# The parts a part's own records count toward, by kind: (column, node kind).
HELD = (
    ("Routes", Kind.ROUTE),
    ("Jobs", Kind.JOB),
    ("Tables", Kind.OBJECT),
    ("Tools", Kind.TOOL),
)
# What a data component is to Backstage: a resource of this type.
RESOURCES = {"database": "database", "cache": "cache", "storage": "bucket"}
# The edges along which a part needs another.
NEEDS = frozenset({EdgeKind.DEPENDS_ON, EdgeKind.CALLS})
API_VERSION = "backstage.io/v1alpha1"


def markdown(model: SystemModel) -> str:
    """What the app is made of, for its docs: its components and services
    by category, each with what it holds."""
    held = _held(model)
    lines = [
        f"# What {model.stack.name} is made of",
        "",
        "Its components and services, read from its code when the docs were "
        "built (`ontology export`).",
    ]
    for category in Category:
        parts = [p for p in _parts(model) if p.category is category]
        if not parts:
            continue
        lines += [
            "",
            f"## {category.value.title() if category is not Category.AI else 'AI'}",
            "",
            "| Part | Kind | What it is | " + " | ".join(c for c, _ in HELD) + " |",
            "|---|---|---|" + "---|" * len(HELD),
        ]
        for part in parts:
            counts = " | ".join(str(held[part.id][kind]) for _, kind in HELD)
            lines.append(
                f"| `{part.name}` | {part.kind.value} | {part.description} | {counts} |"
            )
    return "\n".join(lines) + "\n"


def backstage(model: SystemModel, owner: str = "") -> str:
    """The app as Backstage's catalog has it: the stack a ``System``, each
    service and process a ``Component``, each data store and outside
    provider a ``Resource``. ``owner`` is required there and Aegis has no
    teams: by default a group named for the stack."""
    name = model.stack.name
    owner = owner or f"group:default/{name}"
    entities: list[dict[str, Any]] = [
        _entity(
            "System",
            name,
            {"owner": owner},
            annotations={"backstage.io/techdocs-ref": "dir:."},
        )
    ]
    for part in _parts(model):
        if part.name in RESOURCES:
            spec = {"type": RESOURCES[part.name], "owner": owner, "system": name}
            entities.append(_entity("Resource", part.name, spec, part.description))
            continue
        spec = {
            "type": "service",
            "lifecycle": "experimental" if part.experimental else "production",
            "owner": owner,
            "system": name,
        }
        if needs := _needs(model, part):
            spec["dependsOn"] = needs
        entities.append(_entity("Component", part.name, spec, part.description))
    for outside in (n for n in model.nodes if isinstance(n, ExternalNode)):
        spec = {"type": "external", "owner": owner, "system": name}
        entities.append(_entity("Resource", outside.name, spec))
    return yaml.safe_dump_all(entities, sort_keys=False)


def otel(stack: Stack, unit: str) -> dict[str, str]:
    """The resource attributes one process (``unit``: webserver, worker,
    scheduler) reports its traces under: its own name, in the stack's
    namespace, so the processes of one stack are told apart and kept
    together."""
    return {
        "service.name": unit,
        "service.namespace": stack.name,
        "service.version": stack.build,
        "deployment.environment.name": stack.env,
    }


def _parts(model: SystemModel) -> list[PartNode]:
    """The app's components and services (no sub-part, no shared code)."""
    return [
        n
        for n in model.nodes
        if isinstance(n, PartNode)
        and n.owner is None
        and n.kind in (Kind.COMPONENT, Kind.SERVICE)
    ]


def _roots(model: SystemModel) -> dict[str, str]:
    """Each part's id to the top-level part it is in (itself, or the part
    a sub-part belongs to)."""
    owner = {n.id: n.owner for n in model.nodes if isinstance(n, PartNode)}

    def root(found: str) -> str:
        while owner.get(found):
            found = owner[found]  # type: ignore[assignment]
        return found

    return {part: root(part) for part in owner}


def _held(model: SystemModel) -> dict[str, Counter[Kind]]:
    """Each top-level part's routes, jobs, tables and tools, a sub-part's
    counted toward the part it is in."""
    roots = _roots(model)
    held: dict[str, Counter[Kind]] = {p.id: Counter() for p in _parts(model)}
    for node in model.nodes:
        part = roots.get(node.owner or "")
        if part in held:
            held[part][node.kind] += 1
    return held


def _needs(model: SystemModel, part: PartNode) -> list[str]:
    """What ``part`` (or a part in it) depends on or calls, as Backstage
    references to the entities ``backstage`` makes of them."""
    roots = _roots(model)
    found = {n.id: n for n in model.nodes}
    needs: dict[str, None] = {}
    for edge in model.edges:
        if edge.kind not in NEEDS or roots.get(edge.source) != part.id:
            continue
        target = found.get(roots.get(edge.target, edge.target))
        if isinstance(target, ExternalNode):
            needs[f"resource:{target.name}"] = None
        elif isinstance(target, PartNode) and target.id != part.id:
            kind = "resource" if target.name in RESOURCES else "component"
            needs[f"{kind}:{target.name}"] = None
    return list(needs)


def _entity(
    kind: str,
    name: str,
    spec: dict[str, Any],
    description: str = "",
    annotations: dict[str, str] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"name": name}
    if description:
        metadata["description"] = description
    if annotations:
        metadata["annotations"] = annotations
    return {"apiVersion": API_VERSION, "kind": kind, "metadata": metadata, "spec": spec}
