"""What each part of Redis is for: key families declared by their owners.

A module that writes Redis keys declares them beside the code that writes
them, as ``REDIS_KEYS = (KeyFamily(...), ...)``, and is listed in ``OWNERS``.
The keyspace map (Overseer's Redis page) scans the keys, sorts each into the
first family whose pattern matches, and reads a few samples per family for
size, TTL and how recently it was touched (a picked family's figures:
``redis_facts``). Keys nobody claims are shown as such, which is how a
leftover or a typo gets noticed.
"""

from fnmatch import translate
from functools import cache, lru_cache
from importlib import import_module
import re
from typing import Any

from app.core.config import settings
from app.core.key_family import KeyFamily
from app.core.log import logger
from app.core.series import Sample, Sampler
from app.services.system.models import (
    KeyActivity,
    KeyFamilyRow,
    KeyProbe,
    Keyspace,
    Unclaimed,
)

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
    "app.services.load_test.worker.runs",
    "app.services.system.errors.store",
    "app.components.deploy.agent",
    "app.core.series_keys",
    # Last: the shared cache claims whatever is left in its database.
    "app.services.system.ui_cache",
)

# ponytail: a capped SCAN per database, not a full census; past it, counts
# are the scan's shares scaled to DBSIZE (``estimate``), marked as such.
MAX_KEYS = 10_000
SAMPLES = 5  # keys per family read for TTL and size
ACTIVE_SECONDS = 5  # touched this recently counts as active


@cache
def families() -> tuple[KeyFamily, ...]:
    """Every family the installed owners declare, in ``OWNERS`` order: read
    once, as what is installed does not change while the app runs."""
    found: list[KeyFamily] = []
    for path in OWNERS:
        try:
            module = import_module(path)
        except ImportError:
            continue
        found.extend(getattr(module, "REDIS_KEYS", ()))
    return tuple(found)


def _db(family: KeyFamily) -> int:
    """The logical database a family's keys live in."""
    return int(getattr(settings, family.db, 0))


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
        owner = _claimant(declared, key)
        if owner is None:
            unclaimed.append(key)
        else:
            groups.setdefault(owner, []).append(key)
    return groups, unclaimed


@lru_cache(maxsize=16)
def _matcher(patterns: tuple[str, ...]) -> re.Pattern[str]:
    """Every pattern as one regex, in order: alternation tries them left to
    right, so the first that matches wins, at one match a key."""
    return re.compile(
        "|".join(f"(?P<f{i}>{translate(p)})" for i, p in enumerate(patterns))
    )


def _claimant(
    declared: tuple[KeyFamily, ...] | list[KeyFamily], key: str
) -> int | None:
    """The first family (by index) whose pattern matches ``key``."""
    found = _matcher(tuple(f.pattern for f in declared)).match(key)
    return int(found.lastgroup[1:]) if found and found.lastgroup else None


def family_of(key: str | None, db: int | None = None) -> KeyFamily | None:
    """The family that claims ``key`` in logical database ``db``, as the
    keyspace map sorts it; not knowing the database (the key is gone), never
    one that claims a whole database's leftovers (``"*"``)."""
    if key is None:
        return None
    declared = [
        f for f in families() if (_db(f) == db if db is not None else f.pattern != "*")
    ]
    index = _claimant(declared, key)
    return None if index is None else declared[index]


async def keys_of(client: Any, commands: list[list[Any]]) -> list[list[str]]:
    """Which of each command's arguments are keys, as Redis itself says
    (``COMMAND GETKEYS``, one round trip): streams, scripts and a slow
    log's cut arguments alike; none for a command without keys."""
    pipe = client.pipeline(transaction=False)
    for command in commands:
        pipe.command_getkeys(*command)  # not raw COMMAND: its reply parser
    answers = await pipe.execute(raise_on_error=False)
    return [[decoded(k) for k in a] if isinstance(a, list) else [] for a in answers]


async def homes(keys: list[str]) -> dict[str, int]:
    """The logical database each of ``keys`` is in (the app's or the
    cache's), where one still holds it: a round trip a database."""
    found: dict[str, int] = {}
    for db in _databases(()) if keys else []:
        client = redis_client(db)
        try:
            pipe = client.pipeline(transaction=False)
            for key in keys:
                pipe.exists(key)
            for key, held in zip(keys, await pipe.execute(), strict=True):
                if held:
                    found.setdefault(key, db)
        finally:
            await client.aclose()
    return found


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
    keys: list[str],
    probes: dict[str, KeyProbe],
    idle: dict[str, int | None] | None = None,
    count: int | None = None,
) -> KeyActivity:
    """A family's size and activity from its sampled keys (``probes``) and
    every key's idle seconds (``idle``, beside the probes'); ``count``
    overrides ``len(keys)`` when the keys are a sample."""
    seen = [(k, probes[k]) for k in keys if k in probes]
    sized = [p.bytes for _, p in seen if p.bytes]
    idles = {k: p.idle for k, p in seen} | (idle or {})
    touched = [(i, k) for k in keys if (i := idles.get(k)) is not None]
    latest = min(touched) if touched else None
    count = len(keys) if count is None else count
    return KeyActivity(
        count=count,
        memory=sum(sized) // len(sized) * count if sized else 0,
        ttl=next((p.ttl for _, p in seen if p.ttl >= 0), None),
        idle=latest[0] if latest else None,
        active=latest is not None and latest[0] <= ACTIVE_SECONDS,
        latest=latest[1] if latest else None,
    )


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


def _databases(declared: tuple[KeyFamily, ...] | list[KeyFamily]) -> list[int]:
    names = {"REDIS_DB", "CACHE_REDIS_DB"} | {f.db for f in declared}
    return sorted({int(getattr(settings, n)) for n in names if hasattr(settings, n)})


def redis_client(db: int = 0) -> Any:
    """A Redis client for one read, with timeouts so a hung Redis cannot
    stall a sampler."""
    import redis.asyncio as aioredis

    return aioredis.from_url(
        redis_url(), db=db, socket_timeout=2, socket_connect_timeout=2
    )


async def scan(
    client: Any, pattern: str | None = None, limit: int = MAX_KEYS
) -> list[str]:
    """Up to ``limit`` key names, optionally only those matching ``pattern``."""
    keys: list[str] = []
    async for key in client.scan_iter(match=pattern, count=1000):
        keys.append(key.decode() if isinstance(key, bytes) else key)
        if len(keys) >= limit:
            break
    return keys


async def probe(
    client: Any, groups: list[list[str]]
) -> tuple[dict[str, KeyProbe], dict[str, int | None]]:
    """TTL and size of each group's first samples, and the idle seconds of
    every other key: one hot key among thousands of cold ones is the one
    that says the family is in use, and SCAN order puts it anywhere."""
    detailed = [k for keys in groups for k in keys[:SAMPLES]]
    idle_only = [k for keys in groups for k in keys[SAMPLES:]]
    pipe = client.pipeline(transaction=False)
    for key in detailed:
        pipe.ttl(key)
        pipe.object("idletime", key)
        pipe.memory_usage(key)
    for key in idle_only:
        pipe.object("idletime", key)
    results = await pipe.execute(raise_on_error=False)
    probes: dict[str, KeyProbe] = {}
    for i, key in enumerate(detailed):
        ttl, idle, size = results[i * 3 : i * 3 + 3]
        probes[key] = KeyProbe(
            ttl=ttl if isinstance(ttl, int) else -1,
            idle=idle if isinstance(idle, int) else None,
            bytes=size if isinstance(size, int) else 0,
        )
    rest = results[len(detailed) * 3 :]
    idle = {
        k: i if isinstance(i, int) else None
        for k, i in zip(idle_only, rest, strict=True)
    }
    return probes, idle


async def read_keyspace(cells: int = 42) -> Keyspace:
    """The whole map: each family's figures, the unclaimed keys, the grid."""
    declared = families()
    dbs = [_db(f) for f in declared]
    activity = [KeyActivity() for _ in declared]
    unclaimed: list[str] = []
    stray_count, total, estimated = 0, 0, False
    for db in _databases(declared):
        client = redis_client(db)
        try:
            size = int(await client.dbsize())
            keys = await scan(client)
            total += size
            estimated = estimated or len(keys) < size
            scale = {"scanned": len(keys), "size": size}
            here = [i for i, found in enumerate(dbs) if found == db]
            groups, stray = group_keys([declared[i] for i in here], keys)
            probes, idle = await probe(client, list(groups.values()))
            for local, family_keys in groups.items():
                count = estimate(len(family_keys), **scale)
                activity[here[local]] = summarize(family_keys, probes, idle, count)
            unclaimed += stray
            stray_count += estimate(len(stray), **scale)
        finally:
            await client.aclose()
    rows = [
        KeyFamilyRow(family=f, id=i, db=dbs[i], **dict(activity[i]))
        for i, f in enumerate(declared)
    ]
    grid = waffle([a.count for a in activity] + [stray_count], cells)
    return Keyspace(
        families=rows,
        unclaimed=Unclaimed(count=stray_count, samples=unclaimed[:SAMPLES]),
        cells=["unclaimed" if c == len(rows) else c for c in grid],
        total=total,
        estimated=estimated,
    )


async def sample_keyspace() -> Sample:
    """The keyspace sampler's read: the map as ``latest`` (nothing is
    charted), or what went wrong reading it."""
    try:
        found = await read_keyspace()
    except Exception as exc:  # noqa: BLE001 - shown in the card, logged here
        logger.warning("Redis keyspace read failed", error=str(exc))
        found = Keyspace(error=str(exc))
    return Sample(latest=found)


# One SCAN a tick for every viewer of the Redis page; unwatched, hourly,
# since nothing charts it and the first view takes a sample of its own.
# The name changes when the reading's shape does, so one kept by an older
# build is never read as this one's (it expires on its own).
KEYSPACE = Sampler(
    "redis-keyspace-2", sample_keyspace, interval=3.0, idle_interval=3600.0
)
