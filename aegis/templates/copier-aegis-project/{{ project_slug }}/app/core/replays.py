"""Each request the server answers, kept to replay (Overseer > Replay): the
hops it made (``edges.hop``, which reports here while a request is being
recorded) in the order they ran, each with its real start and length, the
lines of code it was made through and the tables a query touched.

The server's middleware starts a recording per request (``start``) and ends
it (``finish``); it lives in a context variable, so the tasks a request
starts record into it too. Answered, it is kept (``keep``) in the shared
cache, the last ``KEEP`` for a day: Redis on a stack that has it, so a
restart loses none and every process (every replica) reads the same
ones; this process's memory otherwise. The list holds each one's
``Summary``, its hops under a key of its own (``find``): a list is read
far more often than one request. They are read as typed models by
``services.system.kept_requests``. Overseer's own pages and the health
probe are not recorded (they would crowd out the app's), nor is a stream
(it runs for minutes).
"""

from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass, field
import re
import time
from typing import Any
from uuid import uuid4

from app.core.cache import get_cache
from app.core.constants import APIEndpoints
from app.core.key_family import KeyFamily

KEY = "replays:recent"
ONE = "replays:request:"  # + a request's id: the request with its hops
KEEP = 200
KEEP_SECONDS = 86_400
HOPS = 500  # the most a request keeps; the rest are counted
# Not kept: Overseer's own pages and the reads of what the server did
# (kept requests, its metrics: a page polls them), which would crowd out
# the app's, and static files.
SKIPPED = (
    "/overseer",
    "/partials/overseer",
    "/api/v1/requests",
    "/api/v1/metrics",
    "/static",
)
# The container's health probe (``docker-compose.yml``): every 30 seconds,
# it would push out every request a person made within the hour.
PROBES = frozenset({APIEndpoints.HEALTH_BASIC, APIEndpoints.HEALTH_BASIC.rstrip("/")})
ID = r"^[0-9a-f]{32}$"  # a request's id (``uuid4().hex``)
_ID = re.compile(ID)
Line = tuple[str, int]  # a line of the app's code: its path, its number


@dataclass
class Hop:
    chain: tuple[str, ...]  # the parts it ran through, ending where it went
    at_ms: float  # its start, from the request's
    ms: float
    error: bool
    # The lines of the parts' own code it was made through, outermost first.
    trail: tuple[Line, ...]
    tables: list[str] = field(default_factory=list)


@dataclass
class Recording:
    id: str
    method: str
    path: str
    began: float  # ``perf_counter``, for the hops' starts
    route: str = ""
    status: int = 0
    ms: float = 0.0
    hops: list[Hop] = field(default_factory=list)
    dropped: int = 0  # hops past ``HOPS``
    # Answered: what runs on in a copy of its context (a stream's body, a
    # background task) is not its.
    closed: bool = False


@dataclass(frozen=True)
class Summary:
    """A kept request as the list says it: how it was answered, its hops
    counted, not read."""

    id: str
    method: str
    path: str
    route: str
    status: int
    ms: float
    hop_count: int
    dropped: int


def summary(recording: Recording) -> Summary:
    return Summary(
        recording.id,
        recording.method,
        recording.path,
        recording.route,
        recording.status,
        recording.ms,
        len(recording.hops),
        recording.dropped,
    )


REDIS_KEYS = (
    KeyFamily(
        KEY,
        "list",
        "Request replays",
        "The last requests the server answered, newest first, to replay",
        "Replay",
        db="CACHE_REDIS_DB",
        holds="request",
    ),
    KeyFamily(
        ONE + "*",
        "string",
        "A request replayed",
        "One kept request with its hops, while the list keeps it",
        "Replay",
        db="CACHE_REDIS_DB",
    ),
)

_current: ContextVar[Recording | None] = ContextVar("replays", default=None)


def start(method: str, path: str) -> Token[Recording | None] | None:
    """Record the request now starting; None for one not kept."""
    if path.startswith(SKIPPED) or path in PROBES:
        return None
    recording = Recording(uuid4().hex, method, path, time.perf_counter())
    return _current.set(recording)


def finish(
    token: Token[Recording | None] | None,
    *,
    route: str,
    status: int,
    ms: float,
    streamed: bool = False,
) -> Recording | None:
    """End the request ``token`` started: the recording to ``keep`` (none
    for a stream)."""
    if token is None:
        return None
    recording = _current.get()
    _current.reset(token)
    if recording is None:
        return None
    recording.closed = True
    if streamed:
        return None
    recording.route, recording.status, recording.ms = route, status, round(ms, 2)
    return recording


async def keep(recording: Recording) -> None:
    """Keep an answered request, as data a later build can read too; one
    it pushes out of the list goes with its hops."""
    cache = get_cache()
    await cache.set(ONE + recording.id, asdict(recording), KEEP_SECONDS)
    out = await cache.push(KEY, asdict(summary(recording)), KEEP, KEEP_SECONDS)
    for gone in out:
        await cache.invalidate(ONE + str(gone.get("id")))


def current() -> Recording | None:
    """The request being recorded here, if one is (and not yet answered)."""
    recording = _current.get()
    return None if recording is None or recording.closed else recording


def taking() -> bool:
    """Whether a hop now is kept: a request is being recorded, with room
    for it; one past its room is counted, so nothing more is read for it."""
    recording = current()
    if recording is None:
        return False
    if len(recording.hops) >= HOPS:
        recording.dropped += 1
        return False
    return True


def note(
    chain: list[str],
    ms: float,
    error: bool,
    trail: tuple[Line, ...],
    tables: list[str],
) -> None:
    """A hop the request being recorded made, ending now (``taking``)."""
    recording = current()
    if recording is None:
        return
    ended = (time.perf_counter() - recording.began) * 1000
    at = max(ended - ms, 0.0)
    hop = Hop(tuple(chain), round(at, 3), round(ms, 3), error, trail, tables)
    recording.hops.append(hop)


async def recent() -> list[Summary]:
    """The requests kept, newest first; one a build with other fields
    wrote is left out."""
    return [s for kept in await get_cache().listed(KEY) if (s := _listed(kept))]


def is_id(text: str) -> bool:
    """Whether ``text`` could be a request's id: checked before any lookup."""
    return bool(_ID.fullmatch(text))


async def find(request_id: str) -> Recording | None:
    """A kept request with its hops; never looked for unless it is an id."""
    if not is_id(request_id):
        return None
    kept = await get_cache().get(ONE + request_id)
    return _revived(kept) if kept is not None else None


def _listed(kept: dict[str, Any]) -> Summary | None:
    """A listed request as this build's; None for one another build wrote."""
    try:
        return Summary(**kept)
    except TypeError:
        return None


def _revived(kept: dict[str, Any]) -> Recording | None:
    """A kept request as this build's; None for one a build with other
    fields wrote."""
    try:
        return Recording(**{**kept, "hops": [Hop(**hop) for hop in kept["hops"]]})
    except (KeyError, TypeError):
        return None


async def reset() -> None:
    cache = get_cache()
    await cache.invalidate(KEY)
    await cache.invalidate_prefix(ONE)
