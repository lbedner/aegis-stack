"""What a key family holds, in its owner's words: how much is in it now,
how much has gone through it and how recently (Overseer's Redis page, a
picked family's detail).

Read from the data when the family is picked, nothing kept: a stream
counts every entry it was ever given and dates each by its id; a sorted
set whose scores are times counts its members a minute at a time; counters
stored as strings are added up. Each figure counts in the family's word
(``KeyFamily.holds``: "event"), else its type's.
"""

import time
from typing import Any, NamedTuple

from app.core.config import settings
from app.core.formatting import counted, format_ago
from app.core.key_family import KeyFamily
from app.core.log import logger
from app.core.series import sparkline
from app.services.system import redis_keys
from app.services.system.models import (
    EntryRow,
    FamilyDetail,
    FamilyFacts,
    ReaderGroup,
    Tally,
)
from app.services.system.redis_keys import decoded, shown

# ponytail: a family's figures read its first FACT_KEYS keys and a stream's
# newest RECENT_CAP entries of the hour; past either they say so.
FACT_KEYS = 50
RECENT_CAP = 10_000
PEEK_ROWS = 10
MINUTE, HOUR = 60, 3600


class Kind(NamedTuple):
    """A Redis type's entry, singular and plural, and what counts them."""

    noun: str
    plural: str
    counter: str


TYPES = {
    "stream": Kind("entry", "entries", "xlen"),
    "zset": Kind("member", "members", "zcard"),
    "list": Kind("item", "items", "llen"),
    "set": Kind("member", "members", "scard"),
    "hash": Kind("field", "fields", "hlen"),
}
# A string longer than this is a value, not a counter: not fetched to add.
COUNTER_BYTES = 32


class Call(NamedTuple):
    """One command for ``_run``; ``empty`` stands in where it fails (a key
    gone since the scan, or of another type than its family's: arq's queue
    family matches its health-check string)."""

    command: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    empty: Any


def _call(command: str, *args: Any, empty: Any = None, **kwargs: Any) -> Call:
    return Call(command, args, kwargs, empty)


def as_seconds(score: float) -> float | None:
    """A score as a time in Unix seconds, if it is one (seconds or
    milliseconds since 2001); None for a count or anything else."""
    if 1e9 <= score < 1e10:
        return score
    if 1e12 <= score < 1e13:
        return score / 1000
    return None


def entry_time(entry_id: bytes | str) -> float:
    """When a stream entry was added: its id is milliseconds, then a
    sequence."""
    return int(decoded(entry_id).split("-", 1)[0]) / 1000


def per_minute(times: list[float], now: float) -> list[int]:
    """How many of ``times`` fell in each minute of the last hour, oldest
    first."""
    counts = [0] * (HOUR // MINUTE)
    for at in times:
        age = int((now - at) // MINUTE)
        if 0 <= age < len(counts):
            counts[-1 - age] += 1
    return counts


def _ago(at: float | None, now: float) -> str | None:
    return None if at is None else format_ago(max(now - at, 0))


def readable(kind: str, pairs: list[tuple[Any, Any]], now: float) -> list[EntryRow]:
    """A key's entries as table rows: a stream entry's fields as text and
    when it was added, a time score as when; ``when`` None otherwise."""
    if kind == "stream":
        return [
            EntryRow(
                a=decoded(entry_id),
                b=" · ".join(f"{decoded(k)}={shown(v)}" for k, v in fields.items()),
                when=_ago(entry_time(entry_id), now),
            )
            for entry_id, fields in pairs
        ]
    rows = []
    for a, b in pairs:
        timed = as_seconds(b) if kind == "zset" and isinstance(b, float | int) else None
        rows.append(EntryRow(a=shown(a), b=shown(b), when=_ago(timed, now)))
    return rows


async def _run(client: Any, calls: list[Call]) -> list[Any]:
    """``calls`` in one round trip, each answer or its ``empty``."""
    pipe = client.pipeline(transaction=False)
    for call in calls:
        getattr(pipe, call.command)(*call.args, **call.kwargs)
    found = await pipe.execute(raise_on_error=False)
    return [
        call.empty if isinstance(answer, Exception) else answer
        for answer, call in zip(found, calls, strict=True)
    ]


def _lag(lag: int | None) -> str:
    """How far behind a reader group is (Redis 7 says; older does not)."""
    return "unknown" if lag is None else "caught up" if not lag else f"{lag:,} behind"


async def _stream(client: Any, keys: list[str], now: float) -> Tally:
    """Every entry the streams were given and hold, when the newest and
    oldest came, the hour's newest entries a minute at a time, and each
    reader group with its lag: one round trip."""
    since, each = str(int((now - HOUR) * 1000)), max(RECENT_CAP // len(keys), 1)
    found = await _run(
        client,
        [_call("xinfo_stream", k, empty={}) for k in keys]
        + [_call("xrevrange", k, "+", since, each, empty=[]) for k in keys]
        + [_call("xinfo_groups", k, empty=[]) for k in keys],
    )
    n = len(keys)
    infos, recent, readers = found[:n], found[n : 2 * n], found[2 * n :]
    times = [entry_time(entry[0]) for entries in recent for entry in entries]
    firsts = [entry_time(i["first-entry"][0]) for i in infos if i.get("first-entry")]
    lasts = [entry_time(i["last-entry"][0]) for i in infos if i.get("last-entry")]
    groups = [
        ReaderGroup(
            name=decoded(group["name"])
            if n == 1
            else f"{key} · {decoded(group['name'])}",
            consumers=group.get("consumers", 0),
            pending=group.get("pending", 0),
            lag=_lag(group.get("lag")),
        )
        for key, found_groups in zip(keys, readers, strict=True)
        for group in found_groups
    ]
    return Tally(
        held=sum(int(i.get("length") or 0) for i in infos),
        through=sum(int(i.get("entries-added") or i.get("length") or 0) for i in infos),
        minutes=per_minute(times, now),
        capped=any(len(entries) >= each for entries in recent),
        oldest=min(firsts, default=None),
        newest=max(lasts, default=None),
        groups=groups,
    )


async def _zset(client: Any, keys: list[str], now: float) -> Tally:
    """How many members the sets hold; for sets scored by time, the hour's
    a minute at a time (a ``ZCOUNT`` each, nothing fetched) and the oldest
    and newest."""
    found = await _run(
        client,
        [_call("zcard", k, empty=0) for k in keys]
        + [_call("zrange", k, 0, 0, withscores=True, empty=[]) for k in keys]
        + [_call("zrange", k, -1, -1, withscores=True, empty=[]) for k in keys],
    )
    held = sum(found[: len(keys)])
    scores = [ends[0][1] for ends in found[len(keys) :] if ends]
    seconds = [as_seconds(score) for score in scores]
    if not seconds or None in seconds:
        return Tally(held=held)
    unit = scores[0] / seconds[0]  # 1000 for milliseconds
    edges = [(now - HOUR + i * MINUTE) * unit for i in range(HOUR // MINUTE)]
    counts = await _run(
        client,
        [
            _call("zcount", k, low, f"({high}", empty=0)
            for k in keys
            for low, high in zip(
                edges, [*edges[1:], (now + MINUTE) * unit], strict=True
            )
        ],
    )
    return Tally(
        held=held,
        minutes=[sum(counts[i :: len(edges)]) for i in range(len(edges))],
        oldest=min(scores) / unit,
        newest=max(scores) / unit,
    )


async def _counted(client: Any, keys: list[str]) -> Tally:
    """Counters stored as strings, added up; none if any is too long to be
    one (``COUNTER_BYTES``) or is not a number."""
    lengths = await _run(client, [_call("strlen", k, empty=0) for k in keys])
    if any(length > COUNTER_BYTES for length in lengths):
        return Tally()
    try:
        values = await client.mget(keys)
        return Tally(total=sum(float(decoded(v)) for v in values if v is not None))
    except ValueError:
        return Tally()


async def facts(
    family: KeyFamily, client: Any, keys: list[str], *, now: float | None = None
) -> FamilyFacts:
    """``family``'s figures from its first ``FACT_KEYS`` keys, and how many
    were read when it has more (``partial``, else 0)."""
    now = time.time() if now is None else now
    read = keys[:FACT_KEYS]
    tally = Tally()
    kind = family.kind
    if read and kind == "stream":
        tally = await _stream(client, read, now)
    elif read and kind == "zset":
        tally = await _zset(client, read, now)
    elif read and kind == "string":
        tally = await _counted(client, read)
    elif read and kind in TYPES and (kind != "hash" or len(read) == 1):
        counts = await _run(
            client, [_call(TYPES[kind].counter, k, empty=0) for k in read]
        )
        tally = Tally(held=sum(counts))
    return described(family, tally, now, FACT_KEYS if len(keys) > FACT_KEYS else 0)


def _amount(number: float, family: KeyFamily) -> str:
    """``number`` of what the family holds, in its word (``KeyFamily.holds``)
    or its type's, one in the singular."""
    kind = TYPES.get(family.kind)
    noun, plural = "", None
    if family.holds:
        noun = family.holds
    elif kind:
        noun, plural = kind.noun, kind.plural
    if not float(number).is_integer():
        return f"{number:,.2f} {plural or noun + 's'}".strip()
    return counted(int(number), noun, plural) if noun else f"{int(number):,}"


def described(
    family: KeyFamily, tally: Tally, now: float, partial: int = 0
) -> FamilyFacts:
    """The figures ``facts`` read, in words."""
    more = "+" if tally.capped else ""
    figures: list[tuple[str, str]] = []
    if tally.through is not None:
        figures.append(("Through it", _amount(tally.through, family)))
    if tally.minutes is not None:
        figures.append(("Last minute", f"{tally.minutes[-1]:,}{more}"))
        figures.append(("Last hour", f"{sum(tally.minutes):,}{more}"))
    if tally.held is not None:
        figures.append(("Held now", _amount(tally.held, family)))
    if tally.total is not None:
        figures.append(("Total", _amount(tally.total, family)))
    for label, at in (("Newest", tally.newest), ("Oldest", tally.oldest)):
        if (ago := _ago(at, now)) is not None:
            figures.append((label, ago))
    return FamilyFacts(
        figures=figures,
        spark=sparkline([float(n) for n in tally.minutes])
        if tally.minutes is not None
        else None,
        groups=tally.groups,
        partial=partial,
    )


async def _pairs(client: Any, key: str, kind: str) -> list[tuple[Any, Any]]:
    """Up to ``PEEK_ROWS`` of ``key``'s entries, newest first where it has
    an order."""
    n = PEEK_ROWS
    if kind == "zset":
        return await client.zrevrange(key, 0, n - 1, withscores=True)
    if kind == "hash":
        _, found = await client.hscan(key, count=n)
        return list(found.items())[:n]
    if kind == "list":
        return list(enumerate(await client.lrange(key, 0, n - 1)))
    if kind == "set":
        _, members = await client.sscan(key, count=n)
        return [(m, "") for m in members[:n]]
    if kind == "stream":
        return await client.xrevrange(key, count=n)
    if kind == "none":  # gone since it was seen
        return []
    return [(key, await client.get(key))]


async def detail(index: int, latest: str | None = None) -> FamilyDetail | None:
    """A family's figures and the first entries of its most recently
    touched key (``latest``, as the keyspace map last saw it; else the first
    found), in its owner's columns; None for no such family. A family
    holding a credential (``peek=False``) is named, never read."""
    declared = redis_keys.families()
    if not 0 <= index < len(declared):
        return None
    family = declared[index]
    found = FamilyDetail(columns=family.columns)
    if not family.peek:
        return found
    client = redis_keys.redis_client(int(getattr(settings, family.db, 0)))
    try:
        now = time.time()
        keys = await redis_keys.scan(client, family.pattern, limit=FACT_KEYS + 1)
        if key := latest or (keys[0] if keys else None):
            kind = shown(await client.type(key))
            found.key = key
            found.rows = readable(kind, await _pairs(client, key, kind), now)
        found.facts = await facts(family, client, keys, now=now)
    except Exception as exc:  # noqa: BLE001 - shown on the page, not raised
        logger.warning(
            "Redis family read failed", family=family.pattern, error=str(exc)
        )
        found.error = str(exc)
    finally:
        await client.aclose()
    return found
