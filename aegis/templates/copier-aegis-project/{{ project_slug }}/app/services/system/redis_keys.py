"""What each part of Redis is for: key families declared by their owners.

A module that writes Redis keys declares them beside the code that writes
them, as ``REDIS_KEYS = (KeyFamily(...), ...)``, and is listed in ``OWNERS``.
The keyspace map (Overseer's Redis page) scans the keys, sorts each into the
first family whose pattern matches, and reads a few samples per family for
size, TTL and how recently it was touched. Keys nobody claims are shown as
such, which is how a leftover or a typo gets noticed.
"""

from dataclasses import dataclass
from fnmatch import fnmatchcase
from importlib import import_module
from typing import Any

from app.core.config import settings
from app.core.log import logger
from app.core.series import Sample, Sampler

# Modules that declare ``REDIS_KEYS``. Absent ones (a component this stack
# does not have) are skipped.
OWNERS = (
    "app.components.backend.middleware.traffic",
    "app.services.system.health_cache",
    "app.components.worker.events",
    "app.components.worker.heartbeat",
    "app.components.worker.task_history.shared",
    "app.components.worker.middleware",
    "app.components.worker.broker",
    "app.components.worker.registry",
    "app.components.worker.runtime",
    "app.services.system.errors.store",
    # Last: the shared cache claims whatever is left in its database.
    "app.services.system.ui_cache",
)

# ponytail: a capped SCAN per database, not a full census; past it, counts
# are the scan's shares scaled to DBSIZE (``estimate``), marked as such.
MAX_KEYS = 10_000
SAMPLES = 5  # keys per family read for type, TTL and size
ACTIVE_SECONDS = 5  # touched this recently counts as active
PEEK_ROWS = 10


@dataclass(frozen=True)
class KeyFamily:
    """Keys one part of the app owns, in its own words.

    ``db`` names the settings field holding the logical database;
    ``columns`` label a peek at the newest key (a sorted set's member and
    score, a hash's field and value).
    """

    pattern: str
    kind: str
    name: str
    purpose: str
    owner: str
    db: str = "REDIS_DB"
    columns: tuple[str, str] = ("Member", "Value")


def families() -> list[KeyFamily]:
    """Every family the installed owners declare, in ``OWNERS`` order."""
    found: list[KeyFamily] = []
    for path in OWNERS:
        try:
            module = import_module(path)
        except ImportError:
            continue
        found.extend(getattr(module, "REDIS_KEYS", ()))
    return found


def decoded(value: Any) -> str:
    """A reply from a client without ``decode_responses`` as text."""
    return value.decode() if isinstance(value, bytes) else str(value)


def redis_url() -> str:
    """The Redis URL this process should use (host CLI or container)."""
    return getattr(settings, "redis_url_effective", None) or settings.REDIS_URL


def group_keys(
    declared: tuple[KeyFamily, ...] | list[KeyFamily], keys: list[str]
) -> tuple[dict[int, list[str]], list[str]]:
    """Each family's keys (by index) and the keys no family claims."""
    groups: dict[int, list[str]] = {}
    unclaimed: list[str] = []
    for key in keys:
        owner = next(
            (i for i, f in enumerate(declared) if fnmatchcase(key, f.pattern)), None
        )
        if owner is None:
            unclaimed.append(key)
        else:
            groups.setdefault(owner, []).append(key)
    return groups, unclaimed


def waffle(counts: list[int], cells: int = 42) -> list[int | None]:
    """The keyspace grid: which family (by index) each cell shows.

    One cell per key while they fit, so a near-empty Redis looks near-empty;
    past that, cells are shared out by largest remainder, and every family
    with keys keeps at least one.
    """
    total = sum(counts)
    if total <= cells:
        grid: list[int | None] = [i for i, n in enumerate(counts) for _ in range(n)]
        return grid + [None] * (cells - len(grid))
    live = [i for i, n in enumerate(counts) if n]
    shares = {i: max(1, counts[i] * cells // total) for i in live}
    by_remainder = sorted(live, key=lambda i: (counts[i] * cells) % total, reverse=True)
    for i in by_remainder[: cells - sum(shares.values())]:
        shares[i] += 1
    while sum(shares.values()) > cells:
        biggest = max(shares, key=lambda i: shares[i])
        shares[biggest] -= 1
    return [i for i in live for _ in range(shares[i])]


def estimate(count: int, *, scanned: int, size: int) -> int:
    """A family's key count: exact after a full scan, else its share of the
    scanned keys scaled to the database's size."""
    if not scanned or scanned >= size:
        return count
    return round(count * size / scanned)


def summarize(
    keys: list[str], probes: dict[str, dict[str, Any]], count: int | None = None
) -> dict[str, Any]:
    """A family's size and activity from its sampled keys; ``count`` overrides
    ``len(keys)`` when the keys are a sample."""
    seen = [(k, probes[k]) for k in keys if k in probes]
    sized = [int(p["bytes"]) for _, p in seen if p.get("bytes")]
    idle = [(int(p["idle"]), k) for k, p in seen if p.get("idle") is not None]
    latest = min(idle) if idle else None
    ttl = next((p["ttl"] for _, p in seen if p.get("ttl", -1) >= 0), None)
    count = len(keys) if count is None else count
    return {
        "count": count,
        "memory": sum(sized) // len(sized) * count if sized else 0,
        "ttl": ttl,
        "idle": latest[0] if latest else None,
        "active": latest is not None and latest[0] <= ACTIVE_SECONDS,
        "latest": latest[1] if latest else None,
    }


def shown(value: Any, limit: int = 120) -> str:
    """A stored value as text: decoded if it is text, described if not."""
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return f"binary, {len(value)} bytes"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _databases(declared: list[KeyFamily]) -> list[int]:
    names = {"REDIS_DB", "CACHE_REDIS_DB"} | {f.db for f in declared}
    return sorted({int(getattr(settings, n)) for n in names if hasattr(settings, n)})


def redis_client(db: int = 0) -> Any:
    """A Redis client for one read, with timeouts so a hung Redis cannot
    stall a sampler."""
    import redis.asyncio as aioredis

    return aioredis.from_url(
        redis_url(), db=db, socket_timeout=2, socket_connect_timeout=2
    )


async def _scan(
    client: Any, pattern: str | None = None, limit: int = MAX_KEYS
) -> list[str]:
    """Up to ``limit`` key names, optionally only those matching ``pattern``."""
    keys: list[str] = []
    async for key in client.scan_iter(match=pattern, count=1000):
        keys.append(key.decode() if isinstance(key, bytes) else key)
        if len(keys) >= limit:
            break
    return keys


async def _probe(client: Any, groups: list[list[str]]) -> dict[str, dict[str, Any]]:
    """Type, TTL and size of each group's first samples, and the idle time of
    every key: one hot key among thousands of cold ones is the one that says
    the family is in use, and SCAN order puts it anywhere."""
    detailed = [k for keys in groups for k in keys[:SAMPLES]]
    idle_only = [k for keys in groups for k in keys[SAMPLES:]]
    pipe = client.pipeline(transaction=False)
    for key in detailed:
        pipe.type(key)
        pipe.ttl(key)
        pipe.object("idletime", key)
        pipe.memory_usage(key)
    for key in idle_only:
        pipe.object("idletime", key)
    results = await pipe.execute(raise_on_error=False)
    probes: dict[str, dict[str, Any]] = {}
    for i, key in enumerate(detailed):
        kind, ttl, idle, size = results[i * 4 : i * 4 + 4]
        probes[key] = {
            "type": shown(kind),
            "ttl": ttl if isinstance(ttl, int) else -1,
            "idle": idle if isinstance(idle, int) else None,
            "bytes": size if isinstance(size, int) else 0,
        }
    for key, idle in zip(idle_only, results[len(detailed) * 4 :], strict=True):
        probes[key] = {"idle": idle if isinstance(idle, int) else None}
    return probes


async def read_keyspace(cells: int = 42) -> dict[str, Any]:
    """The whole map: each family's figures, the unclaimed keys, the grid."""
    declared = families()
    rows = [
        dict(vars(f), id=i, db=int(getattr(settings, f.db, 0)))
        for i, f in enumerate(declared)
    ]
    for row in rows:
        row |= summarize([], {})
    unclaimed: list[str] = []
    stray_count, total, estimated = 0, 0, False
    for db in _databases(declared):
        client = redis_client(db)
        try:
            size = int(await client.dbsize())
            keys = await _scan(client)
            total += size
            estimated = estimated or len(keys) < size
            scale = {"scanned": len(keys), "size": size}
            here = [(i, f) for i, f in enumerate(declared) if rows[i]["db"] == db]
            groups, stray = group_keys([f for _, f in here], keys)
            probes = await _probe(client, list(groups.values()))
            for local, family_keys in groups.items():
                count = estimate(len(family_keys), **scale)
                rows[here[local][0]] |= summarize(family_keys, probes, count)
            unclaimed += stray
            stray_count += estimate(len(stray), **scale)
        finally:
            await client.aclose()
    counts = [r["count"] for r in rows] + [stray_count]
    grid = waffle(counts, cells)
    return {
        "families": rows,
        "unclaimed": {"count": stray_count, "samples": unclaimed[:SAMPLES]},
        "cells": ["unclaimed" if c == len(rows) else c for c in grid],
        "total": total,
        "estimated": estimated,
    }


async def peek(index: int) -> dict[str, Any] | None:
    """The family's most recently touched key, read in its owner's columns."""
    declared = families()
    if not 0 <= index < len(declared):
        return None
    family = declared[index]
    client = redis_client(int(getattr(settings, family.db, 0)))
    try:
        keys = await _scan(client, family.pattern)
        probes = await _probe(client, [keys])
        key = summarize(keys, probes)["latest"] or (keys[0] if keys else None)
        rows = await _read(client, key) if key else []
    except Exception as exc:  # noqa: BLE001 - shown on the page, not raised
        logger.warning("Redis peek failed", family=family.pattern, error=str(exc))
        return {
            "key": None,
            "columns": list(family.columns),
            "rows": [],
            "error": str(exc),
        }
    finally:
        await client.aclose()
    return {"key": key, "columns": list(family.columns), "rows": rows}


async def _read(client: Any, key: str) -> list[list[str]]:
    """Up to ``PEEK_ROWS`` entries of ``key`` as two-column rows."""
    kind = shown(await client.type(key))
    n = PEEK_ROWS
    if kind == "zset":
        pairs = await client.zrevrange(key, 0, n - 1, withscores=True)
    elif kind == "hash":
        _, found = await client.hscan(key, count=n)
        pairs = list(found.items())[:n]
    elif kind == "list":
        pairs = list(enumerate(await client.lrange(key, 0, n - 1)))
    elif kind == "set":
        _, members = await client.sscan(key, count=n)
        pairs = [(m, "") for m in members[:n]]
    elif kind == "stream":
        pairs = [(i, entry) for i, entry in await client.xrevrange(key, count=n)]
    else:
        pairs = [(key, await client.get(key))]
    return [[shown(a), shown(b)] for a, b in pairs]


async def sample_keyspace() -> Sample:
    """The keyspace sampler's read: the map as ``latest`` (nothing is
    charted), or what went wrong reading it."""
    try:
        found = await read_keyspace()
    except Exception as exc:  # noqa: BLE001 - shown in the card, logged here
        logger.warning("Redis keyspace read failed", error=str(exc))
        found = {"error": str(exc), "families": [], "cells": [], "total": 0}
    return Sample(latest=found)


# One SCAN a tick for every viewer of the Redis page; unwatched, hourly,
# since nothing charts it and the first view takes a sample of its own.
KEYSPACE = Sampler(
    "redis-keyspace", sample_keyspace, interval=3.0, idle_interval=3600.0
)
