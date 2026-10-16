"""Where the live charts' points live (``app.core.series_store``): the raw
hour as a sorted set a series, read by time and trimmed by age; a history
tier as a list a series, appended in time order and cut to its length,
which keeps a week of history small. Redis when the stack has it, this
process's memory otherwise: both read the same."""

from collections.abc import Callable

import pytest

from app.core.series_store import SeriesStore
from tests._fake_redis import FakeRedis


def _memory() -> SeriesStore:
    return SeriesStore()


def _redis() -> SeriesStore:
    store = SeriesStore()
    store._redis, store._store = FakeRedis(), None  # type: ignore[assignment]
    return store


BACKENDS = pytest.mark.parametrize("make", [_memory, _redis], ids=["memory", "redis"])


@BACKENDS
async def test_points_come_back_in_time_order_from_since(
    make: Callable[[], SeriesStore],
) -> None:
    store = make()
    await store.append({"series:a:x": 1.0}, at=100.0, keep_seconds=60, index="i:a")
    await store.append({"series:a:x": 2.0}, at=130.0, keep_seconds=60, index="i:a")
    await store.append({"series:a:y": 5.0}, at=130.0, keep_seconds=60, index="i:a")
    await store.append({"series:b:x": 9.0}, at=130.0, keep_seconds=60, index="i:b")
    assert await store.points("series:a:", since=110.0, index="i:a") == {
        "series:a:x": [(130.0, 2.0)],
        "series:a:y": [(130.0, 5.0)],
    }


@BACKENDS
async def test_a_point_older_than_its_window_is_dropped(
    make: Callable[[], SeriesStore],
) -> None:
    store = make()
    await store.append({"series:a:x": 1.0}, at=100.0, keep_seconds=60, index="i:a")
    await store.append({"series:a:x": 2.0}, at=200.0, keep_seconds=60, index="i:a")
    assert await store.points("series:a:", since=0, index="i:a") == {
        "series:a:x": [(200.0, 2.0)]
    }


@BACKENDS
async def test_a_tier_keeps_its_newest_points_up_to_its_length(
    make: Callable[[], SeriesStore],
) -> None:
    store = make()
    for at in (60.0, 120.0, 180.0):
        await store.push(
            {"series-60:a:x": at / 60}, at=at, length=2, keep_seconds=600, index="t:a"
        )
    assert await store.recent("series-60:a:", since=0, index="t:a") == {
        "series-60:a:x": [(120.0, 2.0), (180.0, 3.0)]
    }
    assert await store.recent("series-60:a:", since=150, index="t:a") == {
        "series-60:a:x": [(180.0, 3.0)]
    }


async def test_a_tier_is_a_list_of_short_entries() -> None:
    """A list of short strings, not a sorted set: a few bytes a point, as
    against the sorted set's hundred and more, where a week of points is."""
    store = _redis()
    await store.push(
        {"series-60:a:x": 12.3456789},
        at=1792090200.0,
        length=10,
        keep_seconds=600,
        index="t:a",
    )
    assert store._redis.lists["series-60:a:x"] == ["1792090200:12.3457"]  # type: ignore[union-attr]
