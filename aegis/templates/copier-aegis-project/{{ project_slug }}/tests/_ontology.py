"""A system model for a test, from its nodes and edges alone; a node or an
edge from its ids; a route's dry path, walked by hand."""

from collections.abc import Iterable

from app.core.ontology.model import (
    Edge,
    EdgeKind,
    ExternalNode,
    Kind,
    Mode,
    Node,
    ObjectNode,
    PartNode,
    Stack,
    SystemModel,
    parse_node_id,
)
from app.core.parts import Category
from app.services.system.dry_path import DryPath, Step
from app.services.system.dry_walk import Hop, HopKind


def model_of(nodes: Iterable[Node] = (), edges: Iterable[Edge] = ()) -> SystemModel:
    return SystemModel(
        partial=False,
        stack=Stack(name="app", env="dev", build="dev", aegis_version="dev"),
        nodes=tuple(nodes),
        edges=tuple(edges),
    )


def node_of(key: str) -> Node:
    """The node ``key`` names: a table, an outside provider or a part."""
    kind, name = parse_node_id(key)
    if kind is Kind.OBJECT:
        return ObjectNode(name=name)
    if kind is Kind.EXTERNAL:
        return ExternalNode(name=name)
    return PartNode(kind=kind, name=name, category=Category.APP)


def edge_of(source: str, target: str, kind: EdgeKind = EdgeKind.CALLS) -> Edge:
    return Edge(source=source, target=target, kind=kind)


def dry_walk(route: str, entry: str, *edges: tuple[str, str]) -> DryPath:
    """``route``'s dry path, its handler in ``entry``, through ``edges``."""
    handler = Hop(
        id=0,
        parent=None,
        kind=HopKind.HANDLER,
        symbol="handler",
        node=entry,
        path="handler.py",
        line=1,
        text="",
    )
    steps = tuple(
        Step(source=a, target=b, kind=HopKind.CALLS, mode=Mode.SYNC) for a, b in edges
    )
    return DryPath(route=route, hops=(handler,), edges=steps, stops=())
