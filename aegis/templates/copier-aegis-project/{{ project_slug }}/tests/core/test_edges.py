"""What the running app does (``app.core.edges``): each hop between parts,
counted where it happens, the caller read from the code on the stack."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from app.core import edges, frames
from app.core.source_index import ROOT
from tests._code import function_at

AI, FINANCE = "app/services/ai/talk.py", "app/services/finance/ledger.py"
WORKER = "app/components/worker/pools.py"
OWNERS = {
    AI: "service:ai",
    FINANCE: "service:finance",
    "app/services/rag/search.py": "service:ai.rag",
    WORKER: "component:worker",
    "app/components/backend/main.py": "component:backend",
    "app/services/system/health.py": "shared:system",
}


@pytest.fixture(autouse=True)
def fresh(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No hops from elsewhere; files owned as ``OWNERS`` says."""
    edges.reset()
    monkeypatch.setattr(
        edges, "_owner", lambda filename: OWNERS.get(filename.removeprefix(f"{ROOT}/"))
    )
    yield
    edges.reset()


def _in(path: str, body: Callable[[], Any]) -> Callable[[], Any]:
    """``body`` called from a frame whose code is in ``path``."""
    return function_at(str(ROOT / path), "    return body()\n", body=body)


def _seen() -> dict[edges.Key, int]:
    return {pair: seen.count for pair, seen in edges._seen.items()}


def test_a_hop_comes_from_the_part_whose_code_made_it() -> None:
    _in(FINANCE, lambda: edges.hop("component:database"))()
    assert _seen() == {("service:finance", "component:database"): 1}


def test_a_nested_call_is_a_hop_between_services() -> None:
    """AI's code calling finance's, which queries: two hops."""
    _in(AI, _in(FINANCE, lambda: edges.hop("component:database")))()
    assert _seen() == {
        ("service:ai", "service:finance"): 1,
        ("service:finance", "component:database"): 1,
    }


def test_a_sub_part_keeps_its_name() -> None:
    _in("app/services/rag/search.py", lambda: edges.hop("component:database"))()
    assert _seen() == {("service:ai.rag", "component:database"): 1}


def test_what_carries_the_call_is_no_hop_of_its_own() -> None:
    """The server running a route, the stack's own code between, the
    worker's enqueue code a service called: only the parts with something
    of their own to say, unless a runner is all there is."""
    call = _in("app/services/system/health.py", lambda: edges.hop("component:database"))
    _in("app/components/backend/main.py", _in(AI, call))()
    _in(AI, _in(WORKER, lambda: edges.hop(edges.QUEUE)))()
    assert _seen() == {
        ("service:ai", "component:database"): 1,
        ("service:ai", edges.QUEUE): 1,
    }
    edges.reset()
    _in("app/components/backend/main.py", lambda: edges.hop("component:database"))()
    assert _seen() == {("component:backend", "component:database"): 1}


async def test_an_async_query_is_a_hop_from_the_code_that_awaited_it(
    tmp_path: Path,
) -> None:
    """An async session runs its statement in a greenlet whose own stack
    stops at SQLAlchemy; the code that awaited it waits on the greenlet
    it switched from, and that is where the caller is read."""
    pytest.importorskip("aiosqlite")  # a Postgres stack has no SQLite driver
    db_activity = pytest.importorskip("app.core.db_activity")  # needs a database
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'hops.db'}")
    db_activity.watch(engine.sync_engine)

    async def query() -> None:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))

    # AI's code awaiting Finance's, awaiting the query.
    scope: dict[str, Any] = {"query": query}
    deep = "async def deep():\n    await query()\n"
    exec(compile(deep, str(ROOT / FINANCE), "exec"), scope)
    exec(compile("async def run():\n    await deep()\n", str(ROOT / AI), "exec"), scope)
    try:
        await scope["run"]()
    finally:
        await engine.dispose()
    # Each frame read once (the greenlet's parent holds the chain of
    # awaits too): no line back from Finance to AI that never ran.
    assert _seen() == {
        ("service:ai", "service:finance"): 1,
        ("service:finance", "component:database"): 1,
    }


def test_past_the_cap_hops_are_counted_as_other() -> None:
    for n in range(edges.CAP + 50):
        edges.hop(f"external:host{n}", via=["service:ai"])
    assert len(edges._seen) == edges.CAP + 1
    assert edges._seen[(edges.OTHER, edges.OTHER)].count == 50


def test_outside_hosts_are_capped_too() -> None:
    names = {edges.outside(f"h{n}.example.com") for n in range(edges.HOST_CAP + 10)}
    assert len(names) == edges.HOST_CAP + 1
    assert "external:other" in names


async def test_every_process_reads_every_processs_hops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each process keeps its own counts under its own key; a reader adds
    them up."""
    from app.core.cache import get_cache

    await get_cache().invalidate_prefix(edges.PREFIX)  # another test's, flushed
    monkeypatch.setattr(frames, "process", lambda: "webserver:1")
    edges.hop("component:database", via=["service:ai"], ms=10)
    await edges.flush()
    monkeypatch.setattr(frames, "process", lambda: "worker:2")
    edges.reset()
    edges.hop("component:database", via=["service:ai"], ms=30, error=True)

    seen = (await edges.observed())[("service:ai", "component:database")]
    assert (seen.count, seen.errors, seen.max_ms, seen.total_ms) == (2, 1, 30, 40)


async def test_with_no_cache_a_reader_has_this_processs_hops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis down, or none (a shell, CI): the others' counts cannot be read,
    so a reader has this process's alone, rather than no answer at all."""
    class _Down:
        async def values_with_prefix(self, prefix: str) -> dict[str, object]:
            raise ConnectionError("no redis")

    edges.reset()
    monkeypatch.setattr(edges, "_remote", (0.0, {}))
    monkeypatch.setattr(edges, "get_cache", lambda: _Down())
    edges.hop("component:database", via=["service:ai"], ms=10)

    seen = await edges.observed()
    assert seen[("service:ai", "component:database")].count == 1


# Calls out over HTTP ---------------------------------------------------------


@pytest.fixture
def providers(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import edges_http

    monkeypatch.setattr(edges_http, "_providers", lambda: {"openai": ("OpenAI", True)})


@pytest.mark.usefixtures("providers")
def test_a_model_provider_called_around_the_ai_service_is_a_bypass() -> None:
    """Finance calling OpenAI itself skips the gateway (its keys, its
    ledger); AI calling it, or RAG in it, is the gateway."""
    import httpx

    from app.core import edges_http

    send = edges_http._timed(
        lambda self, request: httpx.Response(200), lambda r: r.url.host
    )
    request = httpx.Request("GET", "https://api.openai.com/v1/chat")
    for path in (FINANCE, AI, "app/services/rag/search.py"):
        _in(path, lambda: send(None, request))()

    kept = edges._seen
    assert kept[("service:finance", "external:OpenAI")].bypasses == 1
    assert kept[("service:ai", "external:OpenAI")].bypasses == 0
    assert kept[("service:ai.rag", "external:OpenAI")].bypasses == 0


@pytest.mark.usefixtures("providers")
def test_a_host_is_the_part_it_runs_else_its_provider_else_itself() -> None:
    from app.core import edges_http

    assert edges_http.target("postgres") == ("component:database", False)
    assert edges_http.target("api.openai.com") == ("external:OpenAI", True)
    assert edges_http.target("example.org") == ("external:example.org", False)


def test_a_request_is_the_server_serving_the_part_its_route_is_code_of(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.components.backend.middleware.performance import register_middleware
    from app.core import ownership

    app = FastAPI()
    register_middleware(app)

    async def notes() -> dict[str, str]:
        return {}

    notes.__module__ = "app.services.notes.router"
    app.add_api_route("/notes", notes)
    real = ownership.owner
    monkeypatch.setattr(
        ownership,
        "owner",
        lambda where, index=None: ownership.Owner("service", "notes")
        if str(where).startswith("app.services.notes")
        else real(where, index),
    )
    TestClient(app).get("/notes")
    assert _seen()[(edges.SERVER, "service:notes")] == 1
