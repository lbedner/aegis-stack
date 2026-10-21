"""A run's log, kept under its id.

A run is one piece of work someone can look up afterwards: a background
job, a worker task, a scheduled run. Wherever one starts, ``bind_run``
binds its id for the run's duration, and every line logged inside it
(structlog's or the standard library's; ``record_run_line`` sits on the
shared processor chain) is also appended to the sink under that id. The
work itself never knows: a ``logger.info`` inside a task is the whole
contract.

The sink is the storage, not the stream: lines are written as they
happen, whoever is or is not watching, and read back from any index.
Capped at ``MAX_LINES`` (the oldest fall off; the end is where a failure
is) and gone after the run's keep time, the worker task history's. In
memory by default, which is right for a stack whose runs happen in the
one process; ``attach_redis`` (``boot.apply_saved_overrides``) on a
stack whose runs happen in another.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Generator
from contextlib import contextmanager
import sys
from typing import Any

import structlog

from app.core.key_family import KeyFamily

RUN_ID = "run_id"
MAX_LINES = 5000
MAX_RUNS = 200  # in memory: the newest runs, as the job runner keeps jobs
KEEP_SECONDS = 24 * 3600
KEY_PREFIX = "aegis:run:"
# Fields the line's lead already says, or that are about the line, not of it.
_LEAD = ("timestamp", "level", "event")
_SKIPPED = frozenset(
    (
        *_LEAD,
        RUN_ID,
        "logger",
        "pathname",
        "func_name",
        "lineno",
        "exception",
        "emitting_service",
        "app_service",
        "app_component",
        "_record",
        "_from_structlog",
    )
)

REDIS_KEYS = (
    KeyFamily(
        f"{KEY_PREFIX}*",
        "list",
        "Run logs",
        "One list per run: its log lines, oldest first; capped, expires with it",
        "Run log",
        columns=("Index", "Line"),
        holds="line",
    ),
)


class MemorySink:
    """This process's runs, in this process: the newest ``MAX_RUNS``."""

    def __init__(self) -> None:
        self._lines: OrderedDict[str, deque[str]] = OrderedDict()

    def append(self, run_id: str, line: str) -> None:
        if run_id not in self._lines:
            self._lines[run_id] = deque(maxlen=MAX_LINES)
            while len(self._lines) > MAX_RUNS:
                self._lines.popitem(last=False)
        self._lines[run_id].append(line)

    def count(self, run_id: str) -> int:
        return len(self._lines.get(run_id, ()))

    def read(self, run_id: str, start: int = 0) -> list[str]:
        return list(self._lines.get(run_id, ()))[start:]


class RedisSink:
    """Runs shared across processes: one capped list per run, over a
    sync client, since a log processor cannot await."""

    def __init__(self, redis: Any, keep_seconds: int = KEEP_SECONDS) -> None:
        self._redis = redis
        self._keep = keep_seconds
        self._warned = False

    @staticmethod
    def key(run_id: str) -> str:
        return f"{KEY_PREFIX}{run_id}:log"

    def append(self, run_id: str, line: str) -> None:
        # ponytail: one round trip per line, on the loop; buffer and flush
        # if a task ever logs thousands of lines a second.
        key = self.key(run_id)
        pipe = self._redis.pipeline()
        pipe.rpush(key, line)
        pipe.ltrim(key, -MAX_LINES, -1)
        pipe.expire(key, self._keep)
        try:
            pipe.execute()
        except Exception as exc:  # noqa: BLE001 - a log processor cannot log
            if not self._warned:
                sys.stderr.write(f"run log: Redis unreachable, lines dropped: {exc}\n")
            self._warned = True

    def count(self, run_id: str) -> int:
        """Raises ``OSError`` when Redis cannot be reached."""
        with self._reaching():
            return int(self._redis.llen(self.key(run_id)))

    def read(self, run_id: str, start: int = 0) -> list[str]:
        """Raises ``OSError`` when Redis cannot be reached."""
        with self._reaching():
            return list(self._redis.lrange(self.key(run_id), start, -1))

    @contextmanager
    def _reaching(self) -> Generator[None]:
        """A reader learns the store is unreachable as an ``OSError``, so
        it need not know the client (an Overseer partial answers 503)."""
        import redis

        try:
            yield
        except redis.RedisError as exc:
            raise OSError(f"run log store unreachable: {exc}") from exc


_sink: MemorySink | RedisSink = MemorySink()


def sink() -> MemorySink | RedisSink:
    return _sink


def use(target: MemorySink | RedisSink) -> None:
    global _sink
    _sink = target


def attach_redis(url: str, keep_seconds: int = KEEP_SECONDS) -> None:
    """Keep runs in Redis for ``keep_seconds``: in every process of a stack
    that has it, so the webserver reads what a worker or the scheduler
    wrote."""
    import redis

    use(RedisSink(redis.Redis.from_url(url, decode_responses=True), keep_seconds))


def bind(run_id: str) -> None:
    structlog.contextvars.bind_contextvars(**{RUN_ID: run_id})


def unbind() -> None:
    structlog.contextvars.unbind_contextvars(RUN_ID)


@contextmanager
def bind_run(run_id: str | None) -> Generator[None]:
    """Every line logged in here is the run's; nobody's, given no id (a
    run with no record to be found from)."""
    if run_id is None:
        yield
        return
    bind(run_id)
    try:
        yield
    finally:
        unbind()


def render(event_dict: dict[str, Any]) -> str:
    """One line: when, level, what, then the fields; a traceback under it."""
    lead = " ".join(str(event_dict.get(k, "")) for k in _LEAD)
    fields = " ".join(
        f"{k}={v}" for k, v in sorted(event_dict.items()) if k not in _SKIPPED
    )
    line = f"{lead} {fields}".rstrip()
    if trace := event_dict.get("exception"):
        line = f"{line}\n{trace}"
    return line


def record_run_line(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """The processor: a line logged inside a run goes to the sink too."""
    run_id = event_dict.get(RUN_ID)
    if run_id:
        _sink.append(str(run_id), render(event_dict))
    return event_dict
