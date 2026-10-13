"""A system model for a test, from its nodes and edges alone."""

from collections.abc import Iterable

from app.core.ontology.model import Edge, Node, Stack, SystemModel


def model_of(nodes: Iterable[Node] = (), edges: Iterable[Edge] = ()) -> SystemModel:
    return SystemModel(
        partial=False,
        stack=Stack(name="app", env="dev", build="dev", aegis_version="dev"),
        nodes=tuple(nodes),
        edges=tuple(edges),
    )
