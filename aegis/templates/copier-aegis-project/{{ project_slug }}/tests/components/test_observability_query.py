"""The Overseer's Logfire queries stay inside a read token's query budget.

A read token's budget is shared by every process and every stack holding it.
The result cache lived in process memory, so each hot reload started from
nothing and queried again, and the three queries ran at once against the
token's concurrency limit: 429s through a normal working day.
"""

import importlib
from pathlib import Path
from types import ModuleType
from typing import Any, Self

import pytest

import app.services.system.health_observability as observability

TOKEN = "read-token"


class FakeClient:
    """Stands in for ``AsyncLogfireQueryClient``; records every query."""

    queries: list[str] = []
    in_flight = 0
    max_in_flight = 0
    fail = False

    def __init__(self, read_token: str) -> None:
        pass

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def query_json_rows(self, sql: str) -> dict[str, Any]:
        cls = type(self)
        cls.queries.append(sql)
        cls.in_flight += 1
        cls.max_in_flight = max(cls.max_in_flight, cls.in_flight)
        try:
            import asyncio

            await asyncio.sleep(0)
            if cls.fail:
                raise RuntimeError("429 Rate limit exceeded (hour)")
            return {"rows": [{"total_spans": 7}]}
        finally:
            cls.in_flight -= 1


@pytest.fixture
def fresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    """The module as a newly started process sees it, caching under tmp_path."""
    from logfire import query_client

    FakeClient.queries = []
    FakeClient.max_in_flight = 0
    FakeClient.fail = False
    monkeypatch.setattr(query_client, "AsyncLogfireQueryClient", FakeClient)
    monkeypatch.setattr(observability, "_CACHE_DIR", tmp_path)
    return observability


def _restart(module: ModuleType, cache_dir: Path) -> ModuleType:
    """A hot reload: module state from scratch, same cache directory."""
    reloaded = importlib.reload(module)
    reloaded._CACHE_DIR = cache_dir
    return reloaded


async def test_the_three_queries_run_one_at_a_time(fresh: ModuleType) -> None:
    await fresh._query_logfire_trace_data(TOKEN)

    assert len(FakeClient.queries) == 3
    assert FakeClient.max_in_flight == 1


async def test_a_reload_reuses_the_cached_result(
    fresh: ModuleType, tmp_path: Path
) -> None:
    first = await fresh._query_logfire_trace_data(TOKEN)

    again = await _restart(fresh, tmp_path)._query_logfire_trace_data(TOKEN)

    assert len(FakeClient.queries) == 3
    assert again == first


async def test_a_reload_keeps_the_backoff_after_a_failure(
    fresh: ModuleType, tmp_path: Path
) -> None:
    FakeClient.fail = True
    await fresh._query_logfire_trace_data(TOKEN)
    attempts = len(FakeClient.queries)

    await _restart(fresh, tmp_path)._query_logfire_trace_data(TOKEN)

    assert len(FakeClient.queries) == attempts


async def test_a_fresh_result_is_kept_for_ten_minutes(
    fresh: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    start = time.time()
    await fresh._query_logfire_trace_data(TOKEN)
    monkeypatch.setattr(time, "time", lambda: start + 9 * 60)

    await fresh._query_logfire_trace_data(TOKEN)

    assert len(FakeClient.queries) == 3


async def test_only_the_owner_can_read_the_cache(
    fresh: ModuleType, tmp_path: Path
) -> None:
    await fresh._query_logfire_trace_data(TOKEN)

    (cache,) = tmp_path.glob("aegis-logfire-query-*.json")
    assert cache.stat().st_mode & 0o077 == 0
