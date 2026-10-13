"""What runs laid over what is declared: each edge of the model with what
the running app did along it (``edges``), and its ``State``: seen as
declared, seen though never declared (around the plan: a service reaching
another's table, a provider called around the AI service), or declared and
unseen once the build has had a day of traffic (dead).

Declared, besides the model's own edges: a part's tables are its own to
read (``contains``), a table no part owns is anyone's, the server reaching
a part with routes is it serving them, and the queue handing work to a
part is the other half of work handed to it."""

import asyncio
import time

from app.core import edges
from app.core.edges import Key, Seen
from app.core.ontology.model import (
    Edge,
    EdgeKind,
    ExternalNode,
    Kind,
    Node,
    Observed,
    State,
    SystemModel,
    parse_node_id,
)

# How long a build runs with traffic before a declared edge it never used
# is called dead.
DEAD_AFTER = 86_400
# A pair declared more than once carries its traffic on the first of these
# it has: the code's call, which alone can be dead.
DECLARING = (EdgeKind.CALLS, EdgeKind.DEPENDS_ON, EdgeKind.CONTAINS)


async def running() -> SystemModel:
    """The model (``current``) with what this build has done so far: what
    its readers (the API, the MCP tool) give out."""
    from app.core.ontology.system import current

    model = await asyncio.to_thread(current)  # the first build reads the source
    return overlaid(model, await edges.observed(), time.time())


def overlaid(model: SystemModel, seen: dict[Key, Seen], now: float) -> SystemModel:
    """``model``'s edges with ``seen`` laid over them, and each pair seen
    but not declared as an edge of its own (an unknown host its own node)."""
    ids = {n.id for n in model.nodes}
    pairs = _pairs(seen, ids)
    declared = _declared(model, pairs)
    aged = any(now - s.first_seen > DEAD_AFTER for s in pairs.values())
    carriers = _carriers(model.edges)
    found = [
        _laid(e, pairs.get((e.source, e.target)), aged)
        if carriers.get((e.source, e.target)) is e
        else e
        for e in model.edges
    ]
    known = {(e.source, e.target) for e in model.edges}
    extra = [
        Edge(
            source=a,
            target=b,
            kind=EdgeKind.CALLS,
            observed=_observed(s),
            state=_state(s, (a, b) in declared),
        )
        for (a, b), s in sorted(pairs.items())
        if (a, b) not in known
    ]
    hosts: list[Node] = [
        ExternalNode(name=parse_node_id(e.target)[1])
        for e in extra
        if e.target not in ids and e.target.startswith(f"{Kind.EXTERNAL}:")
    ]
    return model.model_copy(
        update={
            "nodes": (*model.nodes, *dict.fromkeys(hosts)),
            "edges": (*found, *extra),
        }
    )


def _pairs(seen: dict[Key, Seen], ids: set[str]) -> dict[Key, Seen]:
    """``seen`` by node: a sub-part with no node of its own as its part
    (``component:scheduler.scheduler``: the scheduler), ``other`` aside."""
    found: dict[Key, Seen] = {}
    for (source, target), counted in seen.items():
        if edges.OTHER not in (source, target):
            pair = (_node(source, ids), _node(target, ids))
            found.setdefault(pair, Seen()).add(counted)
    return found


def _node(node: str, ids: set[str]) -> str:
    if node in ids or node.startswith(f"{Kind.EXTERNAL}:"):
        return node
    part = edges.part_of(node)
    return part if part in ids else node


def _declared(model: SystemModel, pairs: dict[Key, Seen]) -> set[Key]:
    found = {(e.source, e.target) for e in model.edges if e.kind in DECLARING}
    shared = {n.id for n in model.nodes if n.kind is Kind.OBJECT and n.owner is None}
    routed = {n.owner for n in model.nodes if n.kind is Kind.ROUTE and n.owner}
    handed = any(b == edges.QUEUE for _, b in pairs)
    for a, b in pairs:
        if (
            b in shared
            or (a == edges.SERVER and b in routed)
            or (a == edges.QUEUE and handed)
        ):
            found.add((a, b))
    return found


def _carriers(declared: tuple[Edge, ...]) -> dict[Key, Edge]:
    """Each pair's one edge to carry what was seen along it (``DECLARING``)."""
    found: dict[Key, Edge] = {}
    for e in declared:
        held = found.get((e.source, e.target))
        if e.kind in DECLARING and (
            held is None or DECLARING.index(e.kind) < DECLARING.index(held.kind)
        ):
            found[(e.source, e.target)] = e
    return found


def _laid(edge: Edge, seen: Seen | None, aged: bool) -> Edge:
    if seen is None:  # only code's calls can be dead: a process's links carry others'
        dead = aged and edge.kind is EdgeKind.CALLS
        return edge.model_copy(update={"state": State.DECLARED_ONLY if dead else None})
    return edge.model_copy(
        update={"observed": _observed(seen), "state": _state(seen, declared=True)}
    )


def _state(seen: Seen, declared: bool) -> State:
    if seen.bypasses:
        return State.BYPASS
    return State.BOTH if declared else State.OBSERVED_ONLY


def _observed(seen: Seen) -> Observed:
    return Observed(
        count=seen.count,
        errors=seen.errors,
        mean_ms=round(seen.total_ms / seen.count, 1) if seen.count else 0.0,
        max_ms=round(seen.max_ms, 1),
        last_seen=seen.last_seen,
    )
