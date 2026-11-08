"""Walking the system model: the shared walk (``app.core.graph``: a
node's neighbours, the shortest paths between two nodes), and what only
the system model has, a node's wiring (``wiring``), which a path card both
checks when drawn and draws, and each part's top-level part (``roots``).
Pure functions of the model, so the MCP tool, Overseer's map (ON-03) and
the dry path (ON-10) share them."""

from app.core.graph import neighbors, node, paths, touching
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
    it holds; and each queue among them with its tasks."""
    here, edges_of = node(model, node_id), touching(model)
    edges = list(edges_of.get(node_id, []))
    if here.owner and not isinstance(here, PartNode | QueueNode | TaskNode):
        edges += edges_of.get(here.owner, [])
    held = dict.fromkeys(e.target for e in edges if e.kind is EdgeKind.CONTAINS)
    edges += [e for part in held if part != node_id for e in edges_of.get(part, [])]
    ends = {end for e in edges for end in (e.source, e.target)} - {node_id}
    queues = [end for end in ends if parse_node_id(end)[0] is Kind.QUEUE]
    edges += [e for queue in queues for e in edges_of.get(queue, [])]
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
