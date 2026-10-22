"""Each request the server answers, kept to replay (Overseer > Replay): the
hops it made (``edges.hop``, which reports here while a request is being
recorded) in the order they ran, each with its real start and length, the
lines of code it was made through and the tables a query touched.

The server's middleware starts a recording per request (``start``) and ends
it (``finish``); it lives in a context variable, so the tasks a request
starts record into it too. The last ``KEEP`` are kept in this process's
memory. Overseer's own pages are not recorded (they would crowd out the
app's), nor is a stream (it runs for minutes).
"""

from collections import deque
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
import re
import time
from uuid import uuid4

# ponytail: one process's memory, as one webserver process serves the
# app; behind several replicas a request is replayable on the one that
# served it. Shared storage when that is the shape.
KEEP = 200
HOPS = 500  # the most a request keeps; the rest are counted
SKIPPED = ("/overseer", "/partials/overseer", "/static")
_ID = re.compile(r"[0-9a-f]{32}")
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

    @property
    def where(self) -> str | None:
        """The line that made it (the innermost), as ``path:line``."""
        return "{}:{}".format(*self.trail[-1]) if self.trail else None


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


_current: ContextVar[Recording | None] = ContextVar("replays", default=None)
_kept: deque[Recording] = deque(maxlen=KEEP)


def start(method: str, path: str) -> Token[Recording | None] | None:
    """Record the request now starting; None for one not kept."""
    if path.startswith(SKIPPED):
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
) -> str | None:
    """End the request ``token`` started and keep it (not a stream);
    its id."""
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
    _kept.appendleft(recording)
    return recording.id


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


def recent() -> list[Recording]:
    """The requests kept, newest first."""
    return list(_kept)


def is_id(text: str) -> bool:
    """Whether ``text`` could be a request's id: checked before any lookup."""
    return bool(_ID.fullmatch(text))


def find(request_id: str) -> Recording | None:
    """A kept request by its id; never looked for unless it is one."""
    if not is_id(request_id):
        return None
    return next((r for r in _kept if r.id == request_id), None)


def reset() -> None:
    _kept.clear()
