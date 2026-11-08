"""Walking a graph: a node's neighbours and the shortest paths between two
nodes, over its edges either way. Any graph whose nodes have an ``id`` and
whose edges have a ``source`` and a ``target`` will do: the system model
(``app.core.ontology``), or one a service builds of its own. An id is
``<kind>:<name>`` (``node_id``), its kind from the graph's own enum."""

from collections import deque
from collections.abc import Sequence
import difflib
from enum import StrEnum
from typing import Protocol, TypeVar

MAX_DEPTH = 2
MAX_PATHS = 5


class Named(Protocol):
    @property
    def id(self) -> str: ...


class Joining(Protocol):
    @property
    def source(self) -> str: ...

    @property
    def target(self) -> str: ...

    def __hash__(self) -> int: ...


N = TypeVar("N", bound=Named)
E = TypeVar("E", bound=Joining)
K = TypeVar("K", bound=StrEnum)
N_co = TypeVar("N_co", bound=Named, covariant=True)
E_co = TypeVar("E_co", bound=Joining, covariant=True)


class Graph(Protocol[N_co, E_co]):
    @property
    def nodes(self) -> Sequence[N_co]: ...

    @property
    def edges(self) -> Sequence[E_co]: ...


def node_id(kind: StrEnum, name: str) -> str:
    """``<kind>:<name>``: ``person:vale``."""
    return f"{kind.value}:{name}"


def parse_node_id(found: str, kinds: type[K]) -> tuple[K, str]:
    """``node_id`` the other way, in the graph's own kinds: ``(Kind.PERSON, "vale")``."""
    kind, _, name = found.partition(":")
    return kinds(kind), name


class UnknownNodeError(ValueError):
    """An id the graph has no node for; says the closest ones it has."""

    def __init__(self, model: Graph[Named, Joining], node_id: str) -> None:
        close = difflib.get_close_matches(node_id, [n.id for n in model.nodes], n=5)
        hint = f"; closest: {', '.join(close)}" if close else ""
        super().__init__(f"No node {node_id!r}{hint}")


def node(model: Graph[N, E], node_id: str) -> N:
    found = next((n for n in model.nodes if n.id == node_id), None)
    if found is None:
        raise UnknownNodeError(model, node_id)
    return found


def touching(model: Graph[N, E]) -> dict[str, list[E]]:
    """Each node's edges, in and out."""
    found: dict[str, list[E]] = {}
    for edge in model.edges:
        found.setdefault(edge.source, []).append(edge)
        found.setdefault(edge.target, []).append(edge)
    return found


def _other_end(edge: Joining, here: str) -> str:
    return edge.target if edge.source == here else edge.source


def neighbors(
    model: Graph[N, E], node_id: str, depth: int = 1
) -> tuple[N, list[N], list[E]]:
    """``node_id``'s node, the nodes up to ``depth`` edges from it (at most
    ``MAX_DEPTH``) by id, and the edges that reach them."""
    found = node(model, node_id)
    edges_of = touching(model)
    seen, frontier = {node_id}, [node_id]
    edges: dict[E, None] = {}  # each once, in the order reached
    for _ in range(min(max(depth, 1), MAX_DEPTH)):
        reached = []
        for here in frontier:
            for edge in edges_of.get(here, []):
                edges[edge] = None
                if (there := _other_end(edge, here)) not in seen:
                    seen.add(there)
                    reached.append(there)
        frontier = reached
    by_id = {n.id: n for n in model.nodes}
    return found, [by_id[i] for i in sorted(seen - {node_id})], list(edges)


def paths(
    model: Graph[N, E], start: str, end: str, *, directed: bool = False
) -> list[list[E]]:
    """The shortest paths from ``start`` to ``end`` (up to ``MAX_PATHS``),
    each the edges walked, in order, whichever way they point (``directed``:
    only the way they point): one walk keeping each node's edges in from
    the step before, then back from ``end``."""
    node(model, start)
    node(model, end)
    edges_of = touching(model)
    depth = {start: 0}
    before: dict[str, list[E]] = {}  # a node's edges in from one step closer
    queue = deque([start])
    while queue:
        here = queue.popleft()
        if end in depth and depth[here] >= depth[end]:
            break
        for edge in edges_of.get(here, []):
            if directed and edge.source != here:
                continue
            there = _other_end(edge, here)
            if there not in depth:
                depth[there] = depth[here] + 1
                queue.append(there)
            if depth[there] == depth[here] + 1:
                before.setdefault(there, []).append(edge)

    def back(at: str) -> list[list[E]]:
        if at == start:
            return [[]]
        return [
            [*walked, edge]
            for edge in before.get(at, [])
            for walked in back(_other_end(edge, at))
        ][:MAX_PATHS]

    return back(end) if end in depth else []
