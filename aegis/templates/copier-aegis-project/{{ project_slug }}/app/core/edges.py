"""What the running app does: each hop from one part to another (a service
calling another, a query to the database, a call out to a provider, work
handed to the queue), counted where it happens, with no tracing behind it.

``hop`` reads who is calling from the code on the stack (``frames``): the
distinct parts its files belong to (``ownership``), outermost first. A query
finance's code made on a route of AI's is ``ai -> finance -> database``:
service-to-service hops appear without an import hook. What only carries
the call (the server running a route, the worker running a task, the
app's shared code) is no part of the chain unless nothing else is.

Each process counts in its own memory and writes the whole of it to the
shared cache every ``FLUSH_SECONDS`` under its own key a build (Redis when
the stack has it, so the webserver reads the worker's too; this process's
memory otherwise). Never a read-modify-write, so processes never race;
``observed`` adds them up. Bounded: ``CAP`` hops a process, then
``other``; ``HOST_CAP`` outside hosts, then ``external:other``. While a
request is being recorded (``replays``), each hop is noted there too, in
the order it ran.
"""

import asyncio
from dataclasses import dataclass
from functools import cache
import inspect
import time
from typing import Any, Self

from app.core import frames, ownership, replays
from app.core.cache import CACHE_ERRORS, get_cache
from app.core.concurrency import background
from app.core.config import settings
from app.core.key_family import KeyFamily
from app.core.log import logger
from app.core.parts import PARTS

PREFIX = "edges:"
CAP = 2000
HOST_CAP = 50
OTHER = "other"
FLUSH_SECONDS = 10.0
KEEP_SECONDS = 86_400
# What the counts keep in the shared cache, for the keyspace map.
REDIS_KEYS = (
    KeyFamily(
        PREFIX + "*",
        "string",
        "Observed traffic",
        "Each process's counted hops between parts, for the ontology's map",
        "Ontology",
        db="CACHE_REDIS_DB",
    ),
)
QUEUE = "component:queue"  # where work handed off waits (``ontology.parts``)
SERVER = f"component:{ownership.HOST}"
SCHEDULER = "component:scheduler"
DATABASE = "component:database"  # what a query is a hop into (``db_activity``)
# What runs the others' code: dropped from a chain a part is in.
RUNNERS = frozenset(
    f"component:{name}" for name, part in PARTS.items() if part.tier == 1
)

Key = tuple[str, str]  # (from, to)


@dataclass
class Seen:
    count: int = 0
    errors: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    first_seen: float = 0.0
    last_seen: float = 0.0
    bypasses: int = 0  # reached a model provider around the AI service

    def add(self, other: Self) -> None:
        self.count += other.count
        self.errors += other.errors
        self.total_ms += other.total_ms
        self.bypasses += other.bypasses
        self.max_ms = max(self.max_ms, other.max_ms)
        self.last_seen = max(self.last_seen, other.last_seen)
        firsts = [t for t in (self.first_seen, other.first_seen) if t]
        self.first_seen = min(firsts, default=0.0)


_SHARED = f"{ownership.SHARED}:"  # the app's shared code, by its parts' prefix
_seen: dict[Key, Seen] = {}
_hosts: set[str] = set()
_flushed = 0.0
# The other processes' hops as last read: they change once a flush.
_remote: tuple[float, dict[Key, Seen]] = (0.0, {})


def hop(
    to: str,
    *,
    via: list[str] | None = None,
    ms: float = 0.0,
    error: bool = False,
    bypass: bool = False,
    where: replays.Line | None = None,
    lines: list[replays.Line] | None = None,
    tables: list[str] | None = None,
) -> list[str]:
    """Count a hop to ``to`` from the parts on the stack (``on_stack``; or
    ``via``, the callers already known, and their ``lines`` where read
    with them), each between them too; a request being recorded notes it,
    made at ``where`` (else through those lines), with the ``tables`` a
    query touched. Returns the chain counted."""
    if via is None:
        via, lines = on_stack(lines=replays.current() is not None)
    chain = _chain(via, to)
    now = time.time()
    for pair in zip(chain, chain[1:], strict=False):
        _count(pair, now, ms, error, bypass)
    if chain:
        _flush_soon(now)
        if replays.taking():
            if where is None and lines is None:
                lines = on_stack(lines=True)[1]
            trail = (where,) if where else tuple(lines or ())
            replays.note(chain, ms, error, trail, tables or [])
    return chain


def count(source: str, to: str, *, ms: float = 0.0, error: bool = False) -> None:
    """One hop, its source known (a query's table, from what queried it)."""
    _count((source, to), time.time(), ms, error, False)


def on_stack(*, lines: bool = False) -> tuple[list[str], list[replays.Line]]:
    """One read of the stack: the distinct parts whose code is on it and,
    asked for (a request being recorded), the lines of the parts' own code
    (not the app's shared code: what a replayed hop opens a part up
    along), each outermost first."""
    owners: list[str] = []
    found: list[replays.Line] = []
    for frame in frames.frames():
        owner = _owner(frame.f_code.co_filename)
        if not owner:
            continue
        if not owners or owners[-1] != owner:
            owners.append(owner)
        if (
            lines
            and not owner.startswith(_SHARED)
            and (path := frames.app_path(frame.f_code.co_filename))
        ):
            found.append((path, frame.f_lineno))
    return owners[::-1], found[::-1]


def _chain(callers: list[str], to: str) -> list[str]:
    """``callers`` then ``to``: the app's shared code dropped, and the
    runners while a part is calling (all but the outermost where none is),
    each part once in a row."""
    parts = [c for c in callers if not c.startswith(_SHARED)]
    if any(part_of(p) not in RUNNERS for p in parts):
        parts = [p for p in parts if part_of(p) not in RUNNERS]
    else:
        parts = parts[:1]
    chain: list[str] = []
    for part in [*parts, to]:
        if not chain or chain[-1] != part:
            chain.append(part)
    return chain if len(chain) > 1 else []


def part_of(node: str) -> str:
    """A sub-part's part (``service:ai.rag``: ``service:ai``)."""
    return node.partition(".")[0]


@cache
def _owner(filename: str) -> str | None:
    """The part a file is code of (``service:ai.rag``), once a file."""
    where = frames.app_path(filename)
    return _node(ownership.owner(where)) if where and where.startswith("app/") else None


def _node(found: ownership.Owner | None) -> str | None:
    if found is None:
        return None
    return f"{found.kind}:{found.name}" + (f".{found.sub}" if found.sub else "")


def _count(pair: Key, now: float, ms: float, error: bool, bypass: bool) -> None:
    if pair not in _seen and len(_seen) >= CAP:
        pair = (OTHER, OTHER)
    seen = _seen.get(pair) or _seen.setdefault(pair, Seen(first_seen=now))
    seen.count += 1
    seen.errors += error
    seen.bypasses += bypass
    seen.total_ms += ms
    seen.max_ms = max(seen.max_ms, ms)
    seen.last_seen = now


def into(func: Any, *, source: str, ms: float = 0.0, error: bool = False) -> None:
    """A hop from ``source`` into the part ``func`` is code of: the server
    running a route, the queue handing over a task, the scheduler running
    a job. A runner's own code (a wrapper) is no part to go into."""
    target = inspect.unwrap(func) if func else None
    module = getattr(target, "__module__", None)
    node = _node(ownership.owner(module)) if module else None
    if node and not node.startswith(_SHARED) and part_of(node) not in RUNNERS:
        hop(node, via=[source], ms=ms, error=error, where=_defined(target))


def _defined(func: Any) -> replays.Line | None:
    """Where ``func`` is defined in the app's code."""
    code = getattr(func, "__code__", None)
    path = frames.app_path(code.co_filename) if code else None
    return (path, code.co_firstlineno) if code and path else None


def outside(host: str) -> str:
    """An outside host as a node: its own until ``HOST_CAP`` are, then
    ``external:other`` (a crawler fetches any URL)."""
    if host not in _hosts and len(_hosts) >= HOST_CAP:
        return f"external:{OTHER}"
    _hosts.add(host)
    return f"external:{host}"


def _flush_soon(now: float) -> None:
    """Write this process's counts out, at most every ``FLUSH_SECONDS``,
    from a loop where there is one (a sync thread's wait for the next)."""
    global _flushed
    if now - _flushed < FLUSH_SECONDS:
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    _flushed = now
    background(flush())


async def flush() -> None:
    """This process's counts, whole, under its own key for this build."""
    if _seen:
        await get_cache().set(_key(frames.process()), _snapshot(), KEEP_SECONDS)


def _snapshot() -> dict[str, dict[str, float]]:
    return {"|".join(pair): dict(vars(seen)) for pair, seen in _seen.items()}


async def observed() -> dict[Key, Seen]:
    """Every process's hops this build, added up: the others' as last
    written (read again once a flush), this one's as they are now."""
    global _remote
    at, remote = _remote
    if time.time() - at > FLUSH_SECONDS:
        try:
            kept = await get_cache().values_with_prefix(_key(""))
        except CACHE_ERRORS as exc:
            # No cache (a shell, CI): the other processes' counts are
            # unreadable, this one's are still its own.
            logger.warning("Observed calls: the cache did not answer", error=str(exc))
        else:
            kept.pop(_key(frames.process()), None)
            remote = _merged(kept.values())
            _remote = (time.time(), remote)
    found = {pair: Seen(**vars(seen)) for pair, seen in remote.items()}
    for pair, seen in _seen.items():
        found.setdefault(pair, Seen()).add(seen)
    return found


def _merged(snapshots: Any) -> dict[Key, Seen]:
    found: dict[Key, Seen] = {}
    for snapshot in snapshots:
        for name, values in snapshot.items():
            source, _, target = name.partition("|")
            found.setdefault((source, target), Seen()).add(Seen(**values))
    return found


def reset() -> None:
    """Forget this process's hops and the others' as read (a test's start)."""
    global _flushed, _remote
    _seen.clear()
    _hosts.clear()
    _flushed = 0.0
    _remote = (0.0, {})


def _key(process: str) -> str:
    return f"{PREFIX}{settings.BUILD_ID}:{process}"
