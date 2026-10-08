"""The cache view Overseer shows (htmx and Flet): what is in the cache by family, how
much room each family takes, and whether it earns that room (hit rate).

Entries come from ``CacheService.entries`` (sampled past its limit, like
the Redis keyspace map); hits and misses from ``CacheService.stats``,
counted in the process that serves the page.
"""

from typing import Any

from app.core.cache import CacheEntry, CacheStats, cache, family
from app.core.formatting import format_bytes, format_span
from app.core.key_family import KeyFamily

LARGEST = 20

# For the Redis keyspace map: the cache's entries are named by whichever
# service caches them, so the cache claims whatever is left in its
# database. Listed last in ``redis_keys.OWNERS`` so every family declared
# for that database (traffic's counters) keeps its own keys.
REDIS_KEYS = (
    KeyFamily(
        "*",
        "string",
        "Shared cache",
        "Values services cached with app.core.cache; Server > Cache breaks them down",
        "Cache",
        db="CACHE_REDIS_DB",
    ),
)

__all__ = ["LARGEST", "REDIS_KEYS", "family", "load", "summarize"]


def _hit_rate(counts: CacheStats | None) -> float | None:
    if counts is None or counts.hits + counts.misses == 0:
        return None
    return round(100 * counts.hits / (counts.hits + counts.misses), 1)


def summarize(
    backend: str,
    entries: list[CacheEntry],
    truncated: bool,
    stats: dict[str, CacheStats],
) -> dict[str, Any]:
    floor = "+" if truncated else ""
    total = sum(e.size for e in entries)
    groups: dict[str, list[CacheEntry]] = {}
    for entry in entries:
        groups.setdefault(family(entry.key), []).append(entry)
    families = sorted(
        (
            {
                "family": name,
                "keys": len(members),
                "bytes": sum(e.size for e in members),
                "share": sum(e.size for e in members) / total if total else 0,
                "avg_ttl": sum(e.ttl for e in members) / len(members),
                "hits": stats.get(name, CacheStats()).hits,
                "misses": stats.get(name, CacheStats()).misses,
                "hit_rate": _hit_rate(stats.get(name)),
            }
            for name, members in groups.items()
        ),
        key=lambda f: -f["bytes"],
    )
    hits = sum(s.hits for s in stats.values())
    misses = sum(s.misses for s in stats.values())
    overall = _hit_rate(CacheStats(hits=hits, misses=misses))
    return {
        "backend": backend,
        "figures": [
            {"label": "Entries", "value": f"{len(entries):,}{floor}"},
            {"label": "Stored", "value": format_bytes(total) + floor},
            {"label": "Families", "value": len(families)},
            {
                "label": "Hit rate",
                "value": f"{overall}%" if overall is not None else "-",
                "caption": f"{hits + misses:,} reads, this process",
            },
        ],
        "families": [
            f
            | {"size": format_bytes(f["bytes"]), "ttl_label": format_span(f["avg_ttl"])}
            for f in families
        ],
        "largest": [
            {
                "key": e.key,
                "size": format_bytes(e.size),
                "ttl_label": format_span(e.ttl),
                "family": family(e.key),
            }
            for e in sorted(entries, key=lambda e: -e.size)[:LARGEST]
        ],
    }


async def load() -> dict[str, Any]:
    """The shared cache's view, or why it could not be read."""
    try:
        entries, truncated = await cache.entries()
    except Exception as exc:  # noqa: BLE001 - shown on the page, logged by caller
        return {"error": str(exc), "backend": cache.backend_name}
    return {"error": None} | summarize(
        cache.backend_name, entries, truncated, cache.stats()
    )
