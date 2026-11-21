"""Walking the system model: the shared walk (``app.core.graph``: a
node's neighbours, the shortest paths between two nodes), and what only
the system model has, a node's wiring (``wiring``), which a path card both
checks when drawn and draws, and each part's top-level part (``roots``).
Pure functions of the model, so the MCP tool, Overseer's map (ON-03) and
the dry path (ON-10) share them."""

from app.core.graph import neighbors, node, node_id, paths, touching
from app.core.ontology.model import (
    Edge,
    EdgeKind,
    Kind,
    PartNode,
    QueueNode,
    SystemModel,
    TaskNode,
    parse_node_id,
)

__all__ = ["neighbors", "paths", "roots", "wiring"]


def wiring(model: SystemModel, node_id: str) -> list[Edge]:
    """``node_id``'s wiring: its edges; its part's, where it is code the
    map has no box for (a job), which runs as its part does; those of what
    it holds (a service's, only those out of it: what its sub-services
    hold is its insides, a level further); another part's task drawn as
    its queue; and each queue held among them, with its tasks."""
    here, edges_of = node(model, node_id), touching(model)
    inside = _within(edges_of, node_id)
    edges = list(edges_of.get(node_id, []))
    if here.owner and not isinstance(here, PartNode | QueueNode | TaskNode):
        edges += edges_of.get(here.owner, [])
    held = dict.fromkeys(e.target for e in edges if e.kind is EdgeKind.CONTAINS)
    theirs = [e for part in held if part != node_id for e in edges_of.get(part, [])]
    if isinstance(here, PartNode) and here.kind is Kind.SERVICE:
        theirs = [e for e in theirs if not {e.source, e.target} <= inside]
    edges += theirs
    if not isinstance(here, QueueNode):  # a queue's tasks are its own
        tasks = {n.id: n for n in model.nodes if isinstance(n, TaskNode)}
        edges = [e for e in (_from_queue(tasks, e, inside) for e in edges) if e]
    # Opened up only where held (Redis, its queues): a part that uses a
    # queue drew every task on it, others' backups too (2026-11-20).
    queues = {
        e.target
        for e in edges
        if e.kind is EdgeKind.CONTAINS and parse_node_id(e.target)[0] is Kind.QUEUE
    }
    edges += [e for queue in queues - {node_id} for e in edges_of.get(queue, [])]
    return list(dict.fromkeys(edges))


def _from_queue(
    tasks: dict[str, TaskNode], edge: Edge, inside: set[str]
) -> Edge | None:
    """``edge`` with a task from outside ``inside`` drawn as its queue: the
    tasks calling a part are one line from their queue, not one each.
    None where that leaves the queue joined to itself."""
    ends = {
        side: node_id(Kind.QUEUE, task.queue)
        for side in ("source", "target")
        if (end := getattr(edge, side)) not in inside and (task := tasks.get(end))
    }
    moved = edge.model_copy(update=ends) if ends else edge
    return None if moved.source == moved.target else moved


def _within(edges_of: dict[str, list[Edge]], node_id: str) -> set[str]:
    """``node_id`` and all it holds, however deep."""
    found, todo = {node_id}, [node_id]
    while todo:
        here = todo.pop()
        for e in edges_of.get(here, []):
            if (
                e.kind is EdgeKind.CONTAINS
                and e.source == here
                and e.target not in found
            ):
                found.add(e.target)
                todo.append(e.target)
    return found


def roots(model: SystemModel) -> dict[str, str]:
    """Each part's id to the top-level part it is in (itself, or the part
    a sub-part belongs to)."""
    owner = {n.id: n.owner for n in model.nodes if isinstance(n, PartNode)}

    def root(found: str) -> str:
        while owner.get(found):
            found = owner[found]  # type: ignore[assignment]
        return found

    return {part: root(part) for part in owner}
