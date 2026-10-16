"""The cache view Overseer shows (htmx and Flet): what is in the cache,
grouped by what it is for (the key families owners declare, as the Redis
page names them; a prefix where none is declared), how much room each takes,
and whether what is read through the cache earns its room (hit rate).

Entries come from ``CacheService.entries`` (sampled past its limit, like
the Redis keyspace map); hits and misses from ``CacheService.stats``,
counted in the process that serves the page.
"""

from collections.abc import Iterable

from app.core.cache import CacheEntry, CacheStats, cache, family
from app.core.formatting import format_bytes
from app.core.key_family import KeyFamily
from app.services.system import redis_keys
from app.services.system.models import CacheGroup, CacheKey, CacheView

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


def _declared() -> list[KeyFamily]:
    """The families declared for the cache's database, but its catch-all."""
    return [
        f
        for f in redis_keys.families()
        if f.db == "CACHE_REDIS_DB" and f not in REDIS_KEYS
    ]


def _grouped(
    entries: list[CacheEntry],
) -> dict[tuple[str, KeyFamily | None], list[CacheEntry]]:
    """Entries by the family that claims them, else by prefix (``family``)."""
    declared = _declared()
    found = {e.key: e for e in entries}
    claimed, rest = redis_keys.group_keys(declared, list(found))
    groups = {
        (declared[i].name, declared[i]): [found[k] for k in keys]
        for i, keys in claimed.items()
    }
    for key in rest:
        groups.setdefault((family(key), None), []).append(found[key])
    return groups


def _added(counts: Iterable[CacheStats]) -> CacheStats:
    counts = list(counts)
    return CacheStats(
        hits=sum(c.hits for c in counts), misses=sum(c.misses for c in counts)
    )


def _group(
    name: str,
    declared: KeyFamily | None,
    held: list[CacheEntry],
    total: int,
    stats: dict[str, CacheStats],
) -> CacheGroup:
    """One group; its reads are the cache's counts for its keys' prefixes."""
    size = sum(e.size for e in held)
    return CacheGroup(
        name=name,
        family=declared,
        keys=len(held),
        bytes=size,
        share=size / total if total else 0,
        ttl=sum(e.ttl for e in held) / len(held),
        reads=_added(stats[p] for p in {family(e.key) for e in held} if p in stats),
    )


def summarize(
    backend: str,
    entries: list[CacheEntry],
    truncated: bool,
    stats: dict[str, CacheStats],
) -> CacheView:
    """The cache by what each entry is for, largest first."""
    floor = "+" if truncated else ""
    total = sum(e.size for e in entries)
    grouped = _grouped(entries)
    groups = sorted(
        (_group(*kind, held, total, stats) for kind, held in grouped.items()),
        key=lambda g: -g.bytes,
    )
    named = {e.key: name for (name, _), held in grouped.items() for e in held}
    reads = _added(stats.values())
    return CacheView(
        backend=backend,
        figures=[
            {"label": "Entries", "value": f"{len(entries):,}{floor}"},
            {"label": "Stored", "value": format_bytes(total) + floor},
            {"label": "Kinds", "value": len(groups)},
            {
                "label": "Hit rate",
                "value": f"{reads.hit_rate}%" if reads.hit_rate is not None else "-",
                "caption": f"{reads.hits + reads.misses:,} reads, this process",
            },
        ],
        groups=groups,
        largest=[
            CacheKey(key=e.key, bytes=e.size, ttl=e.ttl, group=named[e.key])
            for e in sorted(entries, key=lambda e: -e.size)[:LARGEST]
        ],
    )


async def load() -> CacheView:
    """The shared cache's view, or why it could not be read."""
    try:
        entries, truncated = await cache.entries()
    except Exception as exc:  # noqa: BLE001 - shown on the page, logged by caller
        return CacheView(backend=cache.backend_name, error=str(exc))
    return summarize(cache.backend_name, entries, truncated, cache.stats())
