"""Filters apply to retained occurrences before grouping or pagination, and
pick sources the way Logs does (``ui_logs.Picked``)."""

from starlette.datastructures import QueryParams

from app.services.system.errors.read import search
from app.services.system.errors.store import ErrorStore
from tests._error_store import occurrence


async def _found(store: ErrorStore, query: str) -> set[str]:
    rows, _total = await search(store, QueryParams(query), offset=0, limit=25)
    return {row.latest_id for row in rows}


async def test_filtered_counts_cover_history_before_pagination(
    store: ErrorStore,
) -> None:
    first = occurrence("one", -60)
    await store.insert(first)
    await store.insert(first.model_copy(update={"id": "two", "level": "critical"}))
    rows, total = await search(store, {"level": "critical"}, offset=0, limit=25)
    assert total == 1 and rows[0].count == 1 and rows[0].latest_id == "two"
    assert await _found(store, "q=absent") == set()
    assert await _found(store, "q=FAILED") == {"two"}


async def test_any_picked_source_keeps_an_error(store: ErrorStore) -> None:
    store.max_occurrences = 10
    first = occurrence("server")
    for identity, app_service, page, container in [
        ("ai-web", "ai", "server", "server-1"),
        ("ai-worker", "ai", "worker", "worker-a"),
        ("cache", None, "redis", "redis-1"),
        ("plain", None, "worker", "worker-b"),
    ]:
        await store.insert(
            first.model_copy(
                update={
                    "id": identity,
                    "fingerprint": identity,
                    "app_service": app_service,
                    "page": page,
                    "container_name": container,
                }
            )
        )
    assert await _found(store, "service=redis&service=server") == {"cache", "ai-web"}
    assert await _found(store, "container=worker-b") == {"plain"}
    assert await _found(store, "app_service=ai") == {"ai-web", "ai-worker"}
    assert await _found(store, "app_service=ai&container=worker-b") == {
        "ai-web",
        "ai-worker",
        "plain",
    }
