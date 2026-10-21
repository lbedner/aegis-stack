"""What runs laid over what is declared (``ontology.observed``): each edge
seen or not, and each seen but never declared, by state."""

from app.core.edges import Seen
from app.core.ontology.model import (
    Edge,
    EdgeKind,
    ExternalNode,
    Kind,
    ObjectNode,
    PartNode,
    RouteNode,
    SystemModel,
)
from app.core.ontology.observed import DEAD_AFTER, State, overlaid
from app.core.parts import Category
from tests._ontology import model_of

NOW = 1_000_000.0


def _model() -> SystemModel:
    return model_of(
        (
            PartNode(kind=Kind.COMPONENT, name="backend", category=Category.COMPUTE),
            PartNode(kind=Kind.COMPONENT, name="database", category=Category.DATA),
            PartNode(kind=Kind.SERVICE, name="ai", category=Category.AI),
            PartNode(kind=Kind.SERVICE, name="finance", category=Category.APP),
            ExternalNode(name="OpenAI"),
            ObjectNode(name="ledger", class_name="Ledger", owner="service:finance"),
            ObjectNode(name="user", class_name="User"),
            RouteNode(name="GET /x", method="GET", path="/x", owner="service:ai"),
        ),
        (
            Edge(source="service:ai", target="component:database", kind=EdgeKind.CALLS),
            Edge(source="service:ai", target="external:OpenAI", kind=EdgeKind.CALLS),
            Edge(
                source="service:finance", target="object:ledger", kind=EdgeKind.CONTAINS
            ),
        ),
    )


def _seen(count: int = 1, *, first: float = NOW - 10, bypasses: int = 0) -> Seen:
    return Seen(
        count=count,
        total_ms=10.0 * count,
        max_ms=10.0,
        first_seen=first,
        last_seen=NOW,
        bypasses=bypasses,
    )


def _states(model: SystemModel) -> dict[tuple[str, str], State | None]:
    return {(e.source, e.target): e.state for e in model.edges}


def test_an_edge_seen_and_declared_is_both_and_says_how_much() -> None:
    found = overlaid(_model(), {("service:ai", "component:database"): _seen(4)}, NOW)
    edge = next(e for e in found.edges if e.target == "component:database")
    assert edge.state is State.BOTH
    assert edge.observed is not None
    assert (edge.observed.count, edge.observed.mean_ms) == (4, 10.0)


def test_one_seen_but_never_declared_is_a_bypass_of_the_plan() -> None:
    """Finance reaching AI's database or another part's table is no edge
    the code declares; reading a shared core table is anyone's."""
    found = overlaid(
        _model(),
        {
            ("service:finance", "service:ai"): _seen(),
            ("service:ai", "object:ledger"): _seen(),
            ("service:ai", "object:user"): _seen(),
            ("service:finance", "object:ledger"): _seen(),
            ("component:backend", "service:ai"): _seen(),
        },
        NOW,
    )
    states = _states(found)
    assert states[("service:finance", "service:ai")] is State.OBSERVED_ONLY
    assert states[("service:ai", "object:ledger")] is State.OBSERVED_ONLY
    assert states[("service:ai", "object:user")] is State.BOTH
    assert states[("service:finance", "object:ledger")] is State.BOTH
    assert states[("component:backend", "service:ai")] is State.BOTH  # it has routes


def test_a_model_provider_reached_around_the_gateway_is_flagged() -> None:
    found = overlaid(
        _model(),
        {("service:finance", "external:OpenAI"): _seen(bypasses=1)},
        NOW,
    )
    assert _states(found)[("service:finance", "external:OpenAI")] is State.BYPASS


def test_an_unknown_host_becomes_a_node_of_its_own() -> None:
    found = overlaid(_model(), {("service:ai", "external:example.org"): _seen()}, NOW)
    assert "external:example.org" in {n.id for n in found.nodes}


def test_a_table_the_model_has_no_node_for_is_no_edge() -> None:
    """Postgres reflection reads its catalog (``pg_class``): a table the
    app does not define, so no edge may point at it."""
    found = overlaid(_model(), {("component:backend", "object:pg_class"): _seen()}, NOW)
    ids = {n.id for n in found.nodes}
    assert all(e.source in ids and e.target in ids for e in found.edges)


def test_a_declared_edge_never_seen_is_dead_only_after_a_day_of_traffic() -> None:
    young = {("service:ai", "component:database"): _seen()}
    old = {("service:ai", "component:database"): _seen(first=NOW - DEAD_AFTER - 1)}
    assert (
        _states(overlaid(_model(), young, NOW))[("service:ai", "external:OpenAI")]
        is None
    )
    assert (
        _states(overlaid(_model(), old, NOW))[("service:ai", "external:OpenAI")]
        is State.DECLARED_ONLY
    )


def test_a_sub_part_without_a_node_is_counted_as_its_part() -> None:
    found = overlaid(
        _model(), {("service:ai.voice", "component:database"): _seen()}, NOW
    )
    assert _states(found)[("service:ai", "component:database")] is State.BOTH


def test_a_pair_declared_twice_is_seen_once() -> None:
    """A part both calling and depending on the database: one count, on
    the code's call (the edge that can be dead), not the same traffic on
    two."""
    model = model_of(
        (
            PartNode(kind=Kind.COMPONENT, name="scheduler", category=Category.COMPUTE),
            PartNode(kind=Kind.COMPONENT, name="database", category=Category.DATA),
        ),
        tuple(
            Edge(source="component:scheduler", target="component:database", kind=kind)
            for kind in (EdgeKind.DEPENDS_ON, EdgeKind.CALLS)  # topology first
        ),
    )
    found = overlaid(
        model, {("component:scheduler", "component:database"): _seen(3)}, NOW
    )
    assert [e.kind for e in found.edges if e.observed] == [EdgeKind.CALLS]
