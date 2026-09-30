"""The cache view both Overseers show: what is in the cache by family,
how much room each takes, and whether it earns it (hit rate)."""

from app.core.cache import CacheEntry, CacheStats
from app.services.system import ui_cache


def test_a_family_is_the_first_two_parts_of_a_key() -> None:
    assert ui_cache.family("insights:project:7") == "insights:project"
    assert ui_cache.family("llm:price:gpt-4o") == "llm:price"
    assert ui_cache.family("plain") == "plain"


def test_families_rank_by_room_taken_with_their_hit_rates() -> None:
    entries = [
        CacheEntry("insights:project:1", 900, 200),
        CacheEntry("insights:project:2", 1100, 100),
        CacheEntry("llm:price:gpt-4o", 100, 50),
    ]
    stats = {"insights:project": CacheStats(hits=9, misses=1, sets=2)}
    view = ui_cache.summarize("redis", entries, False, stats)
    first, second = view["families"]
    assert first["family"] == "insights:project" and first["keys"] == 2
    assert first["share"] == 2000 / 2100
    assert first["hit_rate"] == 90.0
    assert second["family"] == "llm:price" and second["hit_rate"] is None


def test_the_largest_keys_come_first() -> None:
    entries = [CacheEntry(f"k:{i}", i * 10, 60) for i in range(30)]
    largest = ui_cache.summarize("memory", entries, False, {})["largest"]
    assert len(largest) == ui_cache.LARGEST
    assert largest[0]["key"] == "k:29"


def test_a_sampled_cache_says_its_numbers_are_a_floor() -> None:
    view = ui_cache.summarize("redis", [CacheEntry("a:b", 1, 1)], True, {})
    assert view["figures"][0]["value"] == "1+"
