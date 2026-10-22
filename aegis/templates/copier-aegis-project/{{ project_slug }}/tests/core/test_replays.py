"""Each request the server answers, kept to replay (``app.core.replays``):
the hops it made (``edges``) in the order they ran, with their real timing."""

from collections.abc import Callable, Iterator
import contextvars
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import structlog

from app.components.backend.middleware.performance import register_middleware
from app.core import edges, ownership, replays
from app.core.source_index import ROOT
from tests._code import function_at

FINANCE = "app/services/finance/ledger.py"
ROUTES = "app/components/backend/api/ledger.py"
OWNERS = {FINANCE: "service:finance", ROUTES: "service:finance"}


@pytest.fixture(autouse=True)
def fresh(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    replays.reset()
    edges.reset()
    monkeypatch.setattr(
        edges, "_owner", lambda filename: OWNERS.get(filename.removeprefix(f"{ROOT}/"))
    )
    yield
    replays.reset()
    edges.reset()


def _in(path: str, body: Callable[[], Any]) -> Callable[[], Any]:
    return function_at(str(ROOT / path), "    return body()\n", body=body)


def _served(path: str, body: Callable[[], Any] = lambda: None) -> replays.Recording:
    token = replays.start("GET", path)
    body()
    assert replays.finish(token, route=path, status=200, ms=12.0) is not None
    return replays.recent()[0]


def test_a_request_keeps_its_hops_in_order_with_where_they_were_made() -> None:
    def work() -> None:
        query = lambda: edges.hop("component:database", ms=2.0, tables=["ledger_entry"])  # noqa: E731
        _in(FINANCE, query)()
        _in(FINANCE, lambda: edges.hop("external:api.stripe.com", ms=5.0))()

    kept = _served("/api/v1/ledger", work)
    assert [hop.chain for hop in kept.hops] == [
        ("service:finance", "component:database"),
        ("service:finance", "external:api.stripe.com"),
    ]
    assert kept.hops[0].tables == ["ledger_entry"]
    assert kept.hops[0].where.startswith(f"{FINANCE}:")
    # Each starts its length before it was noted: they end in the order made.
    assert kept.hops[0].at_ms + 2.0 <= kept.hops[1].at_ms + 5.0
    assert kept.hops[1].ms == 5.0


def test_a_hop_keeps_the_lines_it_was_made_through_outermost_first() -> None:
    """Each line of a part's own code on the stack (not the app's shared
    code, not the tests'): what a replay opens a part up along."""
    made = _in(ROUTES, _in(FINANCE, lambda: edges.hop("component:database")))
    kept = _served("/api/v1/ledger", made)
    assert [path for path, _ in kept.hops[0].trail] == [ROUTES, FINANCE]
    assert kept.hops[0].where == "{}:{}".format(*kept.hops[0].trail[-1])


def test_the_requests_own_hop_opens_at_its_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The server running a route: where it opens is the route's handler,
    not the middleware that saw it end."""
    handler = function_at(str(ROOT / FINANCE), "    return None\n")
    handler.__module__ = "app.services.finance.ledger"
    monkeypatch.setattr(
        edges.ownership, "owner", lambda _: ownership.Owner("service", "finance")
    )
    kept = _served("/r", lambda: edges.into(handler, source=edges.SERVER))
    assert kept.hops[0].chain == (edges.SERVER, "service:finance")
    assert kept.hops[0].where == f"{FINANCE}:1"


def test_past_its_cap_a_query_and_its_tables_are_counted_not_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(replays, "HOPS", 1)

    def work() -> None:
        _in(FINANCE, lambda: edges.hop("component:database", tables=["ledger"]))()
        _in(FINANCE, lambda: edges.hop("component:database", tables=["account"]))()

    kept = _served("/x", work)
    assert [hop.tables for hop in kept.hops] == [["ledger"]]
    assert kept.dropped == 1


def test_what_runs_on_after_the_answer_is_not_kept() -> None:
    """A stream's body or a background task runs on in a copy of the
    request's context after it is answered: the recording is closed."""
    token = replays.start("GET", "/x")
    later = contextvars.copy_context()
    replays.finish(token, route="/x", status=200, ms=1.0)
    later.run(_in(FINANCE, lambda: edges.hop("component:database")))
    assert replays.recent()[0].hops == []


def test_a_failed_hop_says_so() -> None:
    kept = _served(
        "/x", _in(FINANCE, lambda: edges.hop("component:database", error=True))
    )
    assert kept.hops[0].error


def test_nothing_is_kept_outside_a_request() -> None:
    _in(FINANCE, lambda: edges.hop("component:database"))()
    assert replays.recent() == []


def test_overseers_own_pages_and_streams_are_not_kept() -> None:
    """They would crowd out the app's own requests, and a stream runs for
    minutes."""
    assert replays.start("GET", "/overseer/server/backend") is None
    token = replays.start("GET", "/api/v1/events")
    assert (
        replays.finish(token, route="/api/v1/events", status=200, ms=1, streamed=True)
        is None
    )
    assert replays.recent() == []


def test_only_the_last_requests_are_kept_newest_first() -> None:
    for number in range(replays.KEEP + 3):
        _served(f"/r/{number}")
    kept = replays.recent()
    assert len(kept) == replays.KEEP
    assert kept[0].path == f"/r/{replays.KEEP + 2}"


def test_a_request_is_found_by_its_id_and_a_malformed_one_is_not_looked_up() -> None:
    kept = _served("/a")
    assert replays.find(kept.id) is kept
    assert replays.find("0" * 32) is None
    assert replays.find("../etc") is None


def test_the_server_answers_with_the_id_and_logs_carry_it() -> None:
    """Every answer names the request it was (``X-Request-Id``), so what
    sent it (Routes' Execute) can replay it; a line logged while it runs
    carries the same id (structlog's context), so an error links to it."""
    app = FastAPI()
    register_middleware(app)

    @app.get("/logged")
    async def logged() -> dict[str, Any]:
        return structlog.contextvars.get_contextvars()

    response = TestClient(app).get("/logged")
    found = replays.find(response.headers["x-request-id"])
    assert found is not None and found.path == "/logged" and found.status == 200
    assert response.json()["request_id"] == found.id
    assert "request_id" not in structlog.contextvars.get_contextvars()
