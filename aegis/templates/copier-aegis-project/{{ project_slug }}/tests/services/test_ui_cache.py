"""The cache view Overseer shows (htmx and Flet), ``ui_cache``."""

import pytest

from app.core.cache import CacheEntry, CacheStats
from app.core.key_family import KeyFamily
from app.services.system import redis_keys, ui_cache


def test_a_family_is_the_first_two_parts_of_a_key() -> None:
    assert ui_cache.family("insights:project:7") == "insights:project"
    assert ui_cache.family("llm:price:gpt-4o") == "llm:price"
    assert ui_cache.family("plain") == "plain"


def test_keys_group_by_what_they_are_for() -> None:
    """The live charts' many series are one group, named and explained;
    a key no family declares groups by its prefix."""
    entries = [
        CacheEntry("series-hour:containers:redis:app-redis-1:cpu", 900, 3600),
        CacheEntry("series-hour:host:cpu", 100, 3600),
        CacheEntry("insights:project:1", 50, 200),
    ]
    first, second = ui_cache.summarize("redis", entries, False, {}).groups
    assert first.name == "Chart history" and first.keys == 2
    assert first.family and first.family.owner == "Live charts"
    assert first.about and first.family.purpose in first.about
    assert second.name == "insights:project" and second.family is None


def test_only_the_cache_databases_families_name_its_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A family declared for the app's database never claims a cache key
    that happens to match it."""
    elsewhere = KeyFamily("jobs:*", "string", "Jobs", "The app's own", "Worker")
    monkeypatch.setattr(
        redis_keys, "families", lambda: (elsewhere, *ui_cache.REDIS_KEYS)
    )
    view = ui_cache.summarize("redis", [CacheEntry("jobs:1", 10, 60)], False, {})
    assert [g.name for g in view.groups] == ["jobs:1"]


def test_groups_rank_by_room_with_the_hit_rate_of_what_is_read() -> None:
    entries = [
        CacheEntry("insights:project:1", 900, 200),
        CacheEntry("insights:project:2", 1100, 100),
        CacheEntry("llm:price:gpt-4o", 100, 50),
    ]
    stats = {"insights:project": CacheStats(hits=9, misses=1, sets=2)}
    first, second = ui_cache.summarize("redis", entries, False, stats).groups
    assert first.name == "insights:project" and first.keys == 2
    assert first.share == 2000 / 2100
    assert first.hit_rate == 90.0
    assert second.name == "llm:price" and second.hit_rate is None


def test_the_largest_keys_come_first_named_by_their_group() -> None:
    entries = [CacheEntry(f"k:{i}", i * 10, 60) for i in range(30)]
    largest = ui_cache.summarize("memory", entries, False, {}).largest
    assert len(largest) == ui_cache.LARGEST
    assert largest[0].key == "k:29" and largest[0].group == "k:29"


def test_a_sampled_cache_says_its_numbers_are_a_floor() -> None:
    view = ui_cache.summarize("redis", [CacheEntry("a:b", 1, 1)], True, {})
    assert view.figures[0]["value"] == "1+"
