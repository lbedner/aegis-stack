"""Walking the system model: a node's neighbours and the shortest paths
between two nodes, over its edges either way. Pure functions of the model,
so the MCP tool, Overseer's map (ON-03) and the dry path (ON-10) share
them, a node's wiring (``wiring``), which a path card both checks when
drawn and draws, and each part's top-level part (``roots``)."""

from collections import deque
import difflib

from app.core.ontology.model import (
    Edge,
    EdgeKind,
    Kind,
    Node,
    PartNode,
    QueueNode,
    SystemModel,
    TaskNode,
    parse_node_id,
)

MAX_DEPTH = 2
MAX_PATHS = 5


class UnknownNodeError(ValueError):
    """An id the model has no node for; says the closest ones it has."""

    def __init__(self, model: SystemModel, node_id: str) -> None:
        close = difflib.get_close_matches(node_id, [n.id for n in model.nodes], n=5)
        hint = f"; closest: {', '.join(close)}" if close else ""
        super().__init__(f"No node {node_id!r}{hint}")


def node(model: SystemModel, node_id: str) -> Node:
    found = next((n for n in model.nodes if n.id == node_id), None)
    if found is None:
        raise UnknownNodeError(model, node_id)
    return found


def _touching(model: SystemModel) -> dict[str, list[Edge]]:
    """Each node's edges, in and out."""
    found: dict[str, list[Edge]] = {}
    for edge in model.edges:
        found.setdefault(edge.source, []).append(edge)
        found.setdefault(edge.target, []).append(edge)
    return found


def _other(edge: Edge, here: str) -> str:
    return edge.target if edge.source == here else edge.source


def neighbors(
    model: SystemModel, node_id: str, depth: int = 1
) -> tuple[Node, list[Node], list[Edge]]:
    """``node_id``'s node, the nodes up to ``depth`` edges from it (at most
    ``MAX_DEPTH``) by id, and the edges that reach them."""
    found = node(model, node_id)
    touching = _touching(model)
    seen, frontier = {node_id}, [node_id]
    edges: dict[Edge, None] = {}  # each once, in the order reached
    for _ in range(min(max(depth, 1), MAX_DEPTH)):
        reached = []
        for here in frontier:
            for edge in touching.get(here, []):
                edges[edge] = None
                if (there := _other(edge, here)) not in seen:
                    seen.add(there)
                    reached.append(there)
        frontier = reached
    by_id = {n.id: n for n in model.nodes}
    return found, [by_id[i] for i in sorted(seen - {node_id})], list(edges)


def paths(
    model: SystemModel, start: str, end: str, *, directed: bool = False
) -> list[list[Edge]]:
    """The shortest paths from ``start`` to ``end`` (up to ``MAX_PATHS``),
    each the edges walked, in order, whichever way they point (``directed``:
    only the way they point): one walk keeping each node's edges in from
    the step before, then back from ``end``."""
    node(model, start)
    node(model, end)
    touching = _touching(model)
    depth = {start: 0}
    before: dict[str, list[Edge]] = {}  # a node's edges in from one step closer
    queue = deque([start])
    while queue:
        here = queue.popleft()
        if end in depth and depth[here] >= depth[end]:
            break
        for edge in touching.get(here, []):
            if directed and edge.source != here:
                continue
            there = _other(edge, here)
            if there not in depth:
                depth[there] = depth[here] + 1
                queue.append(there)
            if depth[there] == depth[here] + 1:
                before.setdefault(there, []).append(edge)

    def back(at: str) -> list[list[Edge]]:
        if at == start:
            return [[]]
        return [
            [*walked, edge]
            for edge in before.get(at, [])
            for walked in back(_other(edge, at))
        ][:MAX_PATHS]

    return back(end) if end in depth else []


def wiring(model: SystemModel, node_id: str) -> list[Edge]:
    """``node_id``'s wiring: its edges; its part's, where it is code the
    map has no box for (a job), which runs as its part does; those of what
    it holds; and each queue among them with its tasks."""
    here, touching = node(model, node_id), _touching(model)
    edges = list(touching.get(node_id, []))
    if here.owner and not isinstance(here, PartNode | QueueNode | TaskNode):
        edges += touching.get(here.owner, [])
    held = dict.fromkeys(e.target for e in edges if e.kind is EdgeKind.CONTAINS)
    edges += [e for part in held if part != node_id for e in touching.get(part, [])]
    ends = {end for e in edges for end in (e.source, e.target)} - {node_id}
    queues = [end for end in ends if parse_node_id(end)[0] is Kind.QUEUE]
    edges += [e for queue in queues for e in touching.get(queue, [])]
    return list(dict.fromkeys(edges))


def roots(model: SystemModel) -> dict[str, str]:
    """Each part's id to the top-level part it is in (itself, or the part
    a sub-part belongs to)."""
    owner = {n.id: n.owner for n in model.nodes if isinstance(n, PartNode)}

    def root(found: str) -> str:
        while owner.get(found):
            found = owner[found]  # type: ignore[assignment]
        return found

    return {part: root(part) for part in owner}
