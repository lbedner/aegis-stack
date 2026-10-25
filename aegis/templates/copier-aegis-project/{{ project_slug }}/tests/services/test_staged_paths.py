"""A path staged as hops a replay plays (``staged_paths``): a route's code
path, or a flow's stops joined along the lines the model has, a beat
a hop and no timing of its own, in the shape a kept request has
(``kept_requests.RequestHops``)."""

import pytest

from app.core.edges import SERVER
from app.core.ontology.model import EdgeKind, Mode
from app.services.system import staged_paths
from app.services.system.dry_path import Step
from app.services.system.dry_walk import HopKind
from tests._ontology import dry_walk, edge_of, model_of, node_of

AUTH, USERS, DB = "service:auth", "service:auth.users", "component:database"
HOST, STRIPE, USER = "container:webserver", "external:Stripe", "object:user"
TOKENS = "object:refresh_token"


# The Server and Auth in one container; Auth calls the database and holds
# its users (a sub-part) and their table; the Server needs the database.
MODEL = model_of(
    [node_of(k) for k in (SERVER, AUTH, USERS, DB, STRIPE, USER, TOKENS)],
    [
        edge_of(SERVER, HOST, EdgeKind.RUNS_ON),
        edge_of(AUTH, HOST, EdgeKind.RUNS_ON),
        edge_of(SERVER, DB, EdgeKind.DEPENDS_ON),
        edge_of(AUTH, DB),
        edge_of(AUTH, USERS, EdgeKind.CONTAINS),
        edge_of(AUTH, USER, EdgeKind.CONTAINS),
        edge_of(AUTH, TOKENS, EdgeKind.CONTAINS),
    ],
)


def _chains(stops: list[str]) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    staged = staged_paths.joined(MODEL, stops)
    return [(hop.chain, hop.tables) for hop in staged.hops]


def test_a_flow_is_its_stops_joined_along_the_lines_the_model_declares() -> None:
    """The Server reaches what runs in its container; a table a service
    holds is the database read for it, named; a beat a hop."""
    assert _chains([SERVER, AUTH, USER]) == [
        ((SERVER, AUTH), ()),
        ((AUTH, DB), ("user",)),
    ]
    staged = staged_paths.joined(MODEL, [SERVER, AUTH])
    assert [hop.at_ms for hop in staged.hops] == [0.0]
    assert staged.staged


def test_a_read_returns_to_its_reader_drawing_no_line_back() -> None:
    """A table calls nothing: one table to the next is two reads by the
    service holding both, never the database calling back into it."""
    assert _chains([AUTH, USER, TOKENS]) == [
        ((AUTH, DB), ("user",)),
        ((AUTH, DB), ("refresh_token",)),
    ]


def test_a_sub_part_reaches_its_table_through_its_service() -> None:
    assert _chains([USERS, USER]) == [((USERS, AUTH), ()), ((AUTH, DB), ("user",))]


@pytest.mark.parametrize(
    "stops",
    [
        [AUTH, STRIPE],  # no line at all
        [DB, AUTH],  # a call goes one way
    ],
)
def test_a_stop_nothing_reaches_is_refused_saying_what_does(stops: list[str]) -> None:
    """Never a line the model has none for, nor a detour round one (the
    Server to Auth through the database both use)."""
    with pytest.raises(ValueError, match="Nothing on the map") as refused:
        staged_paths.joined(MODEL, stops)
    assert stops[1] in str(refused.value) and "reaches" in str(refused.value)


def test_a_stop_the_model_does_not_have_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="service:auths") as refused:
        staged_paths.joined(MODEL, [SERVER, "service:auths"])
    assert "service:auth" in str(refused.value).split("closest", 1)[1]


def test_a_code_path_leaves_out_what_only_a_registry_reaches() -> None:
    """Every part's health check, looped over where System reads them: the
    card goes into System and stops, the parts behind the loop undrawn."""
    walked = dry_walk(
        "GET /api/v1/ai/chat", "service:ai", ("service:ai", "shared:system")
    )
    fanned = Step(
        source="shared:system",
        target="service:blog",
        kind=HopKind.CALLS,
        mode=Mode.SYNC,
        fanned=True,
    )
    walked = walked.model_copy(update={"edges": (*walked.edges, fanned)})
    chains = [hop.chain for hop in staged_paths.dry(walked).hops]
    assert chains == [(SERVER, "service:ai"), ("service:ai", "shared:system")]


def test_a_dry_path_enters_through_the_server_and_reads_its_tables() -> None:
    """The handler's part is entered from the server; a table read is a hop
    into the database, naming the table, as a kept request's query is."""
    walked = dry_walk("GET /api/v1/auth/me", AUTH, (AUTH, USERS), (USERS, USER))
    staged = staged_paths.dry(walked)
    assert [hop.chain for hop in staged.hops] == [
        (SERVER, AUTH),
        (AUTH, USERS),
        (USERS, DB),
    ]
    assert staged.hops[2].tables == ("user",)
    assert (staged.method, staged.path) == ("GET", "/api/v1/auth/me")
