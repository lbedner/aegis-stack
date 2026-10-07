"""
Tests for CacheService (in-memory dict backend).

All ops are async. These tests exercise the dict-backed path
directly. The Redis-backed singleton is bypassed for the test
session via the ``_no_real_redis`` fixture in
``tests/conftest.py`` — Redis clients bind to an event loop at
import, and pytest-asyncio creates a fresh loop per test, so
running tests through the live Redis singleton breaks. Adding
Redis coverage would need a dedicated test module that opts out
of that fixture.
"""

import asyncio

import pytest

from app.core.cache import CacheService


class TestCacheService:
    @pytest.mark.asyncio
    async def test_set_and_get(self) -> None:
        cache = CacheService()
        await cache.set("key1", {"data": 42})
        assert await cache.get("key1") == {"data": 42}

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_none(self) -> None:
        cache = CacheService()
        assert await cache.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_ttl_expiry(self) -> None:
        cache = CacheService()
        await cache.set("key1", "value", ttl=0)
        await asyncio.sleep(0.01)
        assert await cache.get("key1") is None

    @pytest.mark.asyncio
    async def test_default_ttl(self) -> None:
        cache = CacheService(default_ttl=1)
        await cache.set("key1", "value")
        assert await cache.get("key1") == "value"
        await asyncio.sleep(1.1)
        assert await cache.get("key1") is None

    @pytest.mark.asyncio
    async def test_invalidate(self) -> None:
        cache = CacheService()
        await cache.set("key1", "value")
        await cache.invalidate("key1")
        assert await cache.get("key1") is None

    @pytest.mark.asyncio
    async def test_invalidate_missing_key_no_error(self) -> None:
        cache = CacheService()
        await cache.invalidate("nonexistent")  # should not raise

    @pytest.mark.asyncio
    async def test_clear(self) -> None:
        cache = CacheService()
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.clear()
        assert await cache.get("a") is None
        assert await cache.get("b") is None

    @pytest.mark.asyncio
    async def test_overwrite_existing_key(self) -> None:
        cache = CacheService()
        await cache.set("key1", "old")
        await cache.set("key1", "new")
        assert await cache.get("key1") == "new"

    @pytest.mark.asyncio
    async def test_custom_ttl_overrides_default(self) -> None:
        cache = CacheService(default_ttl=300)
        await cache.set("key1", "value", ttl=0)
        await asyncio.sleep(0.01)
        assert await cache.get("key1") is None

    @pytest.mark.asyncio
    async def test_set_ttl_zero_deletes_existing_key(self) -> None:
        """``ttl=0`` after a normal set must remove the key, not write a
        stale entry that lingers until the next read."""
        cache = CacheService()
        await cache.set("key1", "value", ttl=60)
        assert await cache.get("key1") == "value"
        await cache.set("key1", "newer", ttl=0)
        # No write, no leftover from the previous set — the key is gone.
        assert await cache.get("key1") is None
        # And the underlying store has dropped the entry entirely, not
        # just marked it stale.
        assert "key1" not in cache._store  # type: ignore[operator]

    @pytest.mark.asyncio
    async def test_set_negative_ttl_deletes_existing_key(self) -> None:
        cache = CacheService()
        await cache.set("key1", "value", ttl=60)
        await cache.set("key1", "newer", ttl=-1)
        assert await cache.get("key1") is None
        assert "key1" not in cache._store  # type: ignore[operator]

    @pytest.mark.asyncio
    async def test_invalidate_prefix_dict_backend(self) -> None:
        """Prefix invalidation works on the dict path too."""
        cache = CacheService()
        await cache.set("view:1:overview:7", "a")
        await cache.set("view:1:github:14", "b")
        await cache.set("view:2:overview:7", "c")
        removed = await cache.invalidate_prefix("view:1:")
        assert removed == 2
        assert await cache.get("view:1:overview:7") is None
        assert await cache.get("view:1:github:14") is None
        assert await cache.get("view:2:overview:7") == "c"


class TestCacheInspection:
    """What the Overseer's Cache view reads: every entry's size and time
    left, and per-family hits and misses (this process only)."""

    @pytest.mark.asyncio
    async def test_entries_carry_size_and_time_left(self) -> None:
        cache = CacheService()
        await cache.set("insights:project:7", {"stars": 12}, ttl=300)
        entries, truncated = await cache.entries()
        assert truncated is False
        (entry,) = entries
        assert entry.key == "insights:project:7"
        assert entry.size > 0 and 0 < entry.ttl <= 300

    @pytest.mark.asyncio
    async def test_expired_entries_are_not_listed(self) -> None:
        cache = CacheService()
        await cache.set("gone", 1, ttl=1)
        await asyncio.sleep(1.1)
        assert (await cache.entries())[0] == []

    @pytest.mark.asyncio
    async def test_a_large_cache_is_sampled(self) -> None:
        cache = CacheService()
        for i in range(5):
            await cache.set(f"k:{i}", i)
        entries, truncated = await cache.entries(limit=3)
        assert len(entries) == 3 and truncated is True

    @pytest.mark.asyncio
    async def test_hits_misses_and_sets_are_counted_per_family(self) -> None:
        cache = CacheService()
        await cache.set("insights:project:7", 1)
        await cache.get("insights:project:7")
        await cache.get("insights:project:8")
        stats = cache.stats()["insights:project"]
        assert (stats.hits, stats.misses, stats.sets) == (1, 1, 1)

    def test_the_backend_names_itself(self) -> None:
        assert CacheService().backend_name == "memory"


class TestValuesWithPrefix:
    """Every live value under a prefix, for records kept one per key (the
    Server page's connection history)."""

    async def test_returns_live_values_under_the_prefix(self) -> None:
        cache = CacheService()
        await cache.set("connections:record:a", {"n": 1}, ttl=60)
        await cache.set("connections:record:b", {"n": 2}, ttl=60)
        await cache.set("connections:recent:x", "a", ttl=60)
        await cache.set("other:key", 3, ttl=60)
        assert await cache.values_with_prefix("connections:record:") == {
            "connections:record:a": {"n": 1},
            "connections:record:b": {"n": 2},
        }

    async def test_skips_expired_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cache = CacheService()
        await cache.set("connections:record:old", {"n": 1}, ttl=1)
        monkeypatch.setattr("app.core.cache.time.time", lambda: 10**12)
        assert await cache.values_with_prefix("connections:record:") == {}


class TestSeriesPoints:
    """Time series kept in the cache (``app.core.series`` writes them): a
    sorted set per series under Redis, a list here."""

    async def test_points_come_back_in_time_order_from_since(self) -> None:
        cache = CacheService()
        await cache.append_many({"series:a:x": 1.0}, at=100.0, keep_seconds=60)
        await cache.append_many({"series:a:x": 2.0}, at=130.0, keep_seconds=60)
        await cache.append_many({"series:a:y": 5.0}, at=130.0, keep_seconds=60)
        await cache.append_many({"series:b:x": 9.0}, at=130.0, keep_seconds=60)
        assert await cache.points_with_prefix("series:a:", since=110.0) == {
            "series:a:x": [(130.0, 2.0)],
            "series:a:y": [(130.0, 5.0)],
        }

    async def test_a_point_older_than_its_window_is_dropped(self) -> None:
        cache = CacheService()
        await cache.append_many({"series:a:x": 1.0}, at=100.0, keep_seconds=60)
        await cache.append_many({"series:a:x": 2.0}, at=200.0, keep_seconds=60)
        assert await cache.points_with_prefix("series:a:", since=0) == {
            "series:a:x": [(200.0, 2.0)]
        }

    async def test_a_claim_holds_until_it_expires(self) -> None:
        cache = CacheService()
        assert await cache.claim("series-claim:a", ttl=60) is True
        assert await cache.claim("series-claim:a", ttl=60) is False
