"""The store's Lua against a real Redis (``tests._error_store``)."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest

from app.services.system.errors.store import ErrorStore, StoreUnavailableError
from tests._error_store import occurrence


async def test_atomic_replay_and_equal_looking_real_errors(store: ErrorStore) -> None:
    first = occurrence("a")
    results = await asyncio.gather(*(store.insert(first) for _ in range(8)))
    assert results.count("inserted") == 1
    assert await store.insert(first.model_copy(update={"id": "b"})) == "inserted"
    issues = await store.issues()
    assert len(issues) == 1 and issues[0].count == 2
    assert await store.client.xlen(store.notifications) == 2


async def test_fencing_and_stack_isolation(store: ErrorStore) -> None:
    await store.client.set(store.key("lease"), "owner")
    assert await store.insert(occurrence("a"), token="stale") == "fenced"
    assert await store.insert(occurrence("a"), token="owner") == "inserted"
    other = ErrorStore(
        store.client, "other-" + uuid4().hex, max_occurrences=3, retention_seconds=60
    )
    assert await other.issues() == []


async def test_count_pruning_updates_summary_and_cannot_resurrect(
    store: ErrorStore,
) -> None:
    events = [occurrence(str(i), seconds=i - 10) for i in range(5)]
    for event in events:
        await store.insert(event)
    issues = await store.issues()
    assert issues[0].count == 3
    assert issues[0].first_seen == events[2].timestamp
    assert issues[0].latest_id == "4"
    assert await store.detail("0") is None
    assert await store.insert(events[0]) == "expired"
    assert await store.client.hlen(store.key("records")) == 3
    assert await store.client.zcard(store.key("all")) == 3


async def test_age_pruning_removes_empty_groups(store: ErrorStore) -> None:
    old = occurrence("old", group="old")
    await store.insert(old)
    await store.prune(now=old.timestamp + timedelta(days=8))
    assert await store.issues() == []
    assert await store.detail("old") is None
    assert await store.client.exists(store.key("occurrences:old")) == 0


async def test_pagination_ties_detail_and_size_bound(store: ErrorStore) -> None:
    first = occurrence("a", group="a")
    for group in ("a", "b", "c"):
        await store.insert(first.model_copy(update={"id": group, "fingerprint": group}))
    rows = await store.issues(limit=2)
    assert [row.fingerprint for row in rows] == ["c", "b"]
    assert [row.fingerprint for row in await store.issues(offset=2)] == ["a"]
    assert (await store.detail("a")) == first
    with pytest.raises(ValueError, match="payload limit"):
        await store.insert(first.model_copy(update={"message": "x" * 65536}))


async def test_unavailable_is_controlled() -> None:
    redis = pytest.importorskip("redis.asyncio")
    client = redis.from_url("redis://127.0.0.1:1", socket_connect_timeout=0.1)
    try:
        with pytest.raises(StoreUnavailableError):
            await ErrorStore(
                client, "unavailable", max_occurrences=1, retention_seconds=1
            ).issues()
    finally:
        await client.aclose()


async def test_pruning_drains_multiple_bounded_batches(store: ErrorStore) -> None:
    store.max_occurrences = 200
    first = occurrence("batch", -60)
    for index in range(130):
        await store.insert(first.model_copy(update={"id": str(index)}))
    assert await store.prune(now=first.timestamp + timedelta(days=8)) == 0
    assert await store.client.hlen(store.key("search")) == 0
    assert await store.issues() == []


async def test_burst_enforces_global_bound_and_batched_search(
    store: ErrorStore,
) -> None:
    from time import perf_counter

    from app.services.system.errors.read import search

    store.max_occurrences = 100
    first = occurrence("burst", -2).model_copy(update={"traceback": "frame\n" * 1000})
    began = perf_counter()
    for index in range(1000):
        # Advance source time so count-pruning's conservative tie boundary applies.
        event = first.model_copy(
            update={
                "id": str(index),
                "timestamp": first.timestamp + timedelta(microseconds=index),
            }
        )
        await store.insert(event)
    rows, total = await search(store, {}, offset=0, limit=25)
    assert total == 1 and rows[0].count == 100
    assert await store.client.hlen(store.key("records")) == 100
    assert await store.client.hlen(store.key("search")) == 100
    assert await store.client.xlen(store.notifications) == 1000
    print(
        f"1000-error burst: {perf_counter() - began:.3f}s, 100 retained, {await store.client.memory_usage(store.key('records'))} record bytes"
    )


async def test_the_kept_summaries_and_a_filtered_search_agree(
    store: ErrorStore,
) -> None:
    """No filter reads the summaries each insert keeps; any filter groups
    the search projection itself. One history, one answer either way."""
    from app.services.system.errors.read import search

    store.max_occurrences = 10
    first = occurrence("a", -30)
    for identity, group, seconds in [("a", "x", -30), ("b", "x", -20), ("c", "y", -10)]:
        await store.insert(
            first.model_copy(
                update={
                    "id": identity,
                    "fingerprint": group,
                    "timestamp": first.timestamp + timedelta(seconds=seconds + 30),
                }
            )
        )
    kept, kept_total = await search(store, {}, offset=0, limit=25)
    grouped, grouped_total = await search(store, {"level": "error"}, offset=0, limit=25)
    assert kept_total == grouped_total == 2
    assert kept == grouped
