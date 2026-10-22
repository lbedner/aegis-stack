"""Each request the server answers, kept to replay (``app.core.replays``):
the hops it made (``edges``) in the order they ran, with their real timing."""

from collections.abc import AsyncIterator, Callable
import contextvars
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import structlog

from app.components.backend.middleware.performance import register_middleware
from app.core import edges, ownership, replays
from app.core.cache import get_cache
from app.core.source_index import ROOT
from tests._code import function_at

FINANCE = "app/services/finance/ledger.py"
ROUTES = "app/components/backend/api/ledger.py"
OWNERS = {FINANCE: "service:finance", ROUTES: "service:finance"}


@pytest.fixture(autouse=True)
async def fresh(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    await replays.reset()
    edges.reset()
    monkeypatch.setattr(
        edges, "_owner", lambda filename: OWNERS.get(filename.removeprefix(f"{ROOT}/"))
    )
    yield
    await replays.reset()
    edges.reset()


def _in(path: str, body: Callable[[], Any]) -> Callable[[], Any]:
    return function_at(str(ROOT / path), "    return body()\n", body=body)


def _served(path: str, body: Callable[[], Any] = lambda: None) -> replays.Recording:
    token = replays.start("GET", path)
    body()
    kept = replays.finish(token, route=path, status=200, ms=12.0)
    assert kept is not None
    return kept


async def _found(request_id: str) -> replays.Recording:
    found = await replays.find(request_id)
    assert found is not None
    return found


async def _kept(path: str) -> replays.Recording:
    """A request served and kept, as the server keeps it once answered."""
    kept = _served(path)
    await replays.keep(kept)
    return kept


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
    assert kept.hops[0].trail[-1][0] == FINANCE
    # Each starts its length before it was noted: they end in the order made.
    assert kept.hops[0].at_ms + 2.0 <= kept.hops[1].at_ms + 5.0
    assert kept.hops[1].ms == 5.0


def test_a_hop_keeps_the_lines_it_was_made_through_outermost_first() -> None:
    """Each line of a part's own code on the stack (not the app's shared
    code, not the tests'): what a replay opens a part up along."""
    made = _in(ROUTES, _in(FINANCE, lambda: edges.hop("component:database")))
    kept = _served("/api/v1/ledger", made)
    assert [path for path, _ in kept.hops[0].trail] == [ROUTES, FINANCE]


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
    assert kept.hops[0].trail[-1] == (FINANCE, 1)


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
    kept = replays.finish(token, route="/x", status=200, ms=1.0)
    later.run(_in(FINANCE, lambda: edges.hop("component:database")))
    assert kept is not None and kept.hops == []


def test_a_failed_hop_says_so() -> None:
    kept = _served(
        "/x", _in(FINANCE, lambda: edges.hop("component:database", error=True))
    )
    assert kept.hops[0].error


async def test_nothing_is_kept_outside_a_request() -> None:
    _in(FINANCE, lambda: edges.hop("component:database"))()
    assert replays.current() is None and await replays.recent() == []


async def test_overseers_own_pages_and_streams_are_not_kept() -> None:
    """They would crowd out the app's own requests, and a stream runs for
    minutes."""
    assert replays.start("GET", "/overseer/server/backend") is None
    token = replays.start("GET", "/api/v1/events")
    assert (
        replays.finish(token, route="/api/v1/events", status=200, ms=1, streamed=True)
        is None
    )
    assert await replays.recent() == []


def test_the_containers_health_probe_is_not_kept() -> None:
    """Docker asks every 30 seconds: kept, it would push out every request
    a person made within the hour. A health read that is not the probe
    (the detailed one) is the app's like any other."""
    assert replays.start("GET", "/health/") is None
    assert replays.start("GET", "/health") is None
    assert _served("/health/detailed").path == "/health/detailed"


async def test_only_the_last_requests_are_kept_newest_first() -> None:
    """Listed as summaries (no hops: a list is read far more often than
    one request); one pushed out takes its hops with it."""
    first = await _kept("/r/first")
    for number in range(replays.KEEP + 2):
        await _kept(f"/r/{number}")
    kept = await replays.recent()
    assert len(kept) == replays.KEEP
    assert kept[0] == replays.summary(await _found(kept[0].id))
    assert kept[0].path == f"/r/{replays.KEEP + 1}"
    assert await replays.find(first.id) is None


async def test_a_request_is_found_by_id_and_a_malformed_one_is_not_looked_up() -> None:
    kept = await _kept("/a")
    assert await replays.find(kept.id) == kept
    assert await replays.find("0" * 32) is None
    assert await replays.find("../etc") is None


async def test_a_kept_request_outlives_the_process_that_served_it() -> None:
    """Kept where every process reads it (the shared cache: Redis on a
    stack that has it), with its hops, so a restart loses nothing; one a
    build with other fields wrote is left out, not misread."""
    kept = _served("/a", _in(FINANCE, lambda: edges.hop("component:database")))
    await replays.keep(kept)
    await get_cache().push(replays.KEY, {"id": "0" * 32, "new": 1}, 5, 60)
    assert await replays.recent() == [replays.summary(kept)]
    assert await replays.find(kept.id) == kept


async def test_the_server_answers_with_the_id_and_logs_carry_it() -> None:
    """Every answer names the request it was (``X-Request-Id``), so what
    sent it (Routes' Execute) can replay it; a line logged while it runs
    carries the same id (structlog's context), so an error links to it."""
    app = FastAPI()
    register_middleware(app)

    @app.get("/logged")
    async def logged() -> dict[str, Any]:
        return structlog.contextvars.get_contextvars()

    response = TestClient(app).get("/logged")
    found = await replays.find(response.headers["x-request-id"])
    assert found is not None and found.path == "/logged" and found.status == 200
    assert response.json()["request_id"] == found.id
    assert "request_id" not in structlog.contextvars.get_contextvars()
