"""The walk over any graph whose nodes have ids and whose edges have two
ends: built here from plain records, not the system model, since a
service may build a graph of its own (a story's cast, say)."""

from dataclasses import dataclass
from enum import StrEnum

import pytest

from app.core import graph


class Kind(StrEnum):
    PERSON = "person"
    HOUSE = "house"


@dataclass(frozen=True)
class Node:
    id: str


@dataclass(frozen=True)
class Edge:
    source: str
    target: str


@dataclass(frozen=True)
class Graph:
    nodes: list[Node]
    edges: list[Edge]


VALE, ERRANI, RANON, HOUSE = (
    graph.node_id(Kind.PERSON, "vale"),
    graph.node_id(Kind.PERSON, "errani"),
    graph.node_id(Kind.PERSON, "ranon"),
    graph.node_id(Kind.HOUSE, "aran"),
)
FAMILY = Graph(
    nodes=[Node(VALE), Node(ERRANI), Node(RANON), Node(HOUSE)],
    edges=[Edge(VALE, ERRANI), Edge(VALE, RANON), Edge(VALE, HOUSE)],
)


def test_an_id_is_its_kind_and_name_both_ways() -> None:
    assert VALE == "person:vale"
    assert graph.parse_node_id(VALE, Kind) == (Kind.PERSON, "vale")


def test_neighbors_are_the_nodes_an_edge_away_either_way() -> None:
    here, near, edges = graph.neighbors(FAMILY, ERRANI)

    assert here == Node(ERRANI)
    assert near == [Node(VALE)]
    assert edges == [Edge(VALE, ERRANI)]


def test_a_path_walks_edges_either_way_unless_directed() -> None:
    assert graph.paths(FAMILY, ERRANI, RANON) == [
        [Edge(VALE, ERRANI), Edge(VALE, RANON)]
    ]
    assert graph.paths(FAMILY, ERRANI, RANON, directed=True) == []


def test_an_unknown_id_names_the_closest_ones() -> None:
    with pytest.raises(graph.UnknownNodeError, match="closest: person:vale"):
        graph.neighbors(FAMILY, "person:val")
