"""Where the live charts' points live (``app.core.series_store``): Redis
when the stack has it, this process's memory otherwise; both read the
same."""

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
    for at, points, index in (
        (100.0, {"series-hour:a:x": 1.0}, "i:a"),
        (130.0, {"series-hour:a:x": 2.0, "series-hour:a:y": 5.0}, "i:a"),
        (130.0, {"series-hour:b:x": 9.0}, "i:b"),
    ):
        await store.push(points, at=at, length=10, keep_seconds=60, index=index)
    assert await store.recent("series-hour:a:", since=110.0, index="i:a") == {
        "series-hour:a:x": [(130.0, 2.0)],
        "series-hour:a:y": [(130.0, 5.0)],
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


async def test_a_series_is_a_list_of_short_entries() -> None:
    """A list of short strings, not a sorted set (``series_store``)."""
    store = _redis()
    await store.push(
        {"series-60:a:x": 12.3456789},
        at=1792090200.0,
        length=10,
        keep_seconds=600,
        index="t:a",
    )
    assert store._redis.lists["series-60:a:x"] == ["1792090200:12.3456789"]  # type: ignore[union-attr]


@BACKENDS
async def test_a_read_can_take_just_the_newest_points(
    make: Callable[[], SeriesStore],
) -> None:
    """A chart's window needs the list's tail, not the whole hour."""
    store = make()
    for at in range(10):
        await store.push(
            {"series-hour:a:x": float(at)},
            at=at,
            length=10,
            keep_seconds=60,
            index="i:a",
        )
    found = await store.recent("series-hour:a:", since=0, index="i:a", count=3)
    assert found == {"series-hour:a:x": [(7.0, 7.0), (8.0, 8.0), (9.0, 9.0)]}


@BACKENDS
async def test_a_running_total_keeps_what_its_rate_needs(
    make: Callable[[], SeriesStore],
) -> None:
    """A byte counter read twice a second apart: its rate comes from the
    difference, so the total keeps every byte and the time its fraction."""
    store = make()
    for at, total in ((1792090200.25, 123456789012.0), (1792090201.5, 123456790036.0)):
        await store.push(
            {"series-hour:a:rx": total}, at=at, length=10, keep_seconds=60, index="i:a"
        )
    (t1, v1), (t2, v2) = (await store.recent("series-hour:a:", since=0, index="i:a"))[
        "series-hour:a:rx"
    ]
    assert (v2 - v1) / (t2 - t1) == 1024 / 1.25
