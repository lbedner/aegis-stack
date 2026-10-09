"""Database activity worth a look: a transaction held longer than
``DATABASE_SLOW_TRANSACTION_SECONDS``, and a statement that found the
database locked, each with the process and the app code behind it; and,
on SQLite, every transaction held right now (``held``).

SQLite keeps no record of who held its lock, so a "database is locked"
failure used to be guessed at from timestamps. ``watch`` times every
transaction on an engine and catches lock failures; ``recent`` reads what
was recorded, for the Database pages. SQLite cannot say who holds its lock
either, so each process keeps its own open transactions and publishes the
ones held past ``SHOWN_AFTER``, refreshed while held, gone once they end
or their process stops refreshing them. Records go through the shared cache
(Redis when the stack has it, so the webserver sees what the worker and
scheduler recorded; this process's memory otherwise) and expire after an
hour. Each is also logged, so a process without an event loop to write the
record from still leaves one.
"""

import asyncio
import os
import socket
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from types import FrameType
from typing import Any

from sqlalchemy import Engine, event

from app.core.cache import get_cache
from app.core.concurrency import background
from app.core.config import settings
from app.core.log import logger

PREFIX = "db_activity:"
KEEP_SECONDS = 3600
SHOWN = 50
# The project root: a caller is the innermost frame in the app's own code.
ROOT = Path(__file__).resolve().parents[2]
DATABASE_LAYER = ("app/core/db.py", "app/core/db_activity.py")
# Transactions held now, one key a process: shown once held this long,
# looked at this often while any is open, and kept this long past the
# last look (a process that stopped).
HELD = "db_held:"
SHOWN_AFTER = 1.0
SWEEP = 1.0
KEEP_HELD = 5
# This container (Docker names it by its id): which one to restart.
HOST = socket.gethostname()
_open: dict[int, dict[str, Any]] = {}
_published = False
# The loop a sweep is armed on, while one is; the loop a sync session's
# thread schedules on (the last one seen running).
_sweeper: asyncio.AbstractEventLoop | None = None
_loop: asyncio.AbstractEventLoop | None = None


def watch(engine: Engine) -> None:
    """Time every transaction on ``engine`` and catch its lock failures."""
    event.listen(engine, "begin", _began)
    event.listen(engine, "commit", _ended)
    event.listen(engine, "rollback", _ended)
    event.listen(engine, "handle_error", _failed)
    if engine.dialect.name == "sqlite":  # Postgres says who: pg_stat_activity
        # Ahead of the engine's own BEGIN, which is where the wait happens.
        event.listen(engine, "begin", _waits_on_itself, insert=True)
        event.listen(engine, "begin", _opened)
        event.listen(engine, "commit", _closed)
        event.listen(engine, "rollback", _closed)


def is_slow(seconds: float) -> bool:
    """Held past ``DATABASE_SLOW_TRANSACTION_SECONDS`` (0: never)."""
    limit = settings.DATABASE_SLOW_TRANSACTION_SECONDS
    return bool(limit) and seconds >= limit


def _began(conn: Any) -> None:
    conn.info["began_at"] = time.monotonic()


def _ended(conn: Any) -> None:
    began = conn.info.pop("began_at", None)
    if began is not None and is_slow(held := time.monotonic() - began):
        _record("slow", round(held, 2))


def _failed(context: Any) -> None:
    if "database is locked" in str(context.original_exception):
        _record("locked", None)


def _record(kind: str, seconds: float | None) -> None:
    entry = {
        "kind": kind,
        "seconds": seconds,
        "process": process(),
        "caller": _caller(_frames()),
        "at": datetime.now(UTC).isoformat(),
    }
    logger.warning("Database activity", **entry)
    try:
        asyncio.get_running_loop()
    except RuntimeError:  # no loop to write from: the log line is the record
        return
    key = f"{PREFIX}{entry['at']}:{uuid.uuid4().hex[:8]}"
    background(get_cache().set(key, entry, KEEP_SECONDS))


def _task() -> asyncio.Task[Any] | None:
    try:
        return asyncio.current_task()
    except RuntimeError:  # a thread with no loop: a sync session's
        return None


def _waits_on_itself(conn: Any) -> None:
    """A task opening a locking transaction while it holds one: SQLite has
    one writer, so it waits out the busy timeout behind itself and fails."""
    task = _task()
    if (
        conn.dialect.is_async
        and task is not None
        and any(e["locks"] and e["task"] is task for e in _open.values())
    ):
        _record("self_wait", None)


def _opened(conn: Any) -> None:
    """Noted, cheaply: who holds it is read only once it is held long."""
    global _sweeper
    _open[id(conn)] = {
        "began": datetime.now(UTC).isoformat(),
        "at": time.monotonic(),
        # The async engine begins IMMEDIATE: it holds the write lock now.
        "locks": bool(conn.dialect.is_async),
        "task": _task(),
        "thread": threading.get_ident(),
    }
    if _sweeper is None or _sweeper.is_closed():
        _sweeper = _soon(SWEEP, _sweep)


def _closed(conn: Any) -> None:
    _open.pop(id(conn), None)  # the next sweep publishes the change


def _soon(delay: float, fn: Callable[[], None]) -> asyncio.AbstractEventLoop | None:
    """``fn`` on this process's loop after ``delay``, from any thread (a
    sync session runs in one): the loop it runs on, or None before any."""
    global _loop
    try:
        _loop = asyncio.get_running_loop()
        _loop.call_later(delay, fn)
    except RuntimeError:
        if _loop is None or _loop.is_closed():
            return None
        _loop.call_soon_threadsafe(_loop.call_later, delay, fn)
    return _loop


def _sweep() -> None:
    """Publish, and look again while anything is open."""
    global _sweeper
    _publish()
    _sweeper = _soon(SWEEP, _sweep) if _open else None


def _publish() -> None:
    """This process's transactions held past ``SHOWN_AFTER``, each with
    where its holder is now, or none."""
    global _published
    now = time.monotonic()
    key = f"{HELD}{process()}"
    shown = [
        {
            "process": process(),
            "host": HOST,
            "caller": _caller(_holding(entry)),
            "began": entry["began"],
            "locks": entry["locks"],
        }
        for entry in list(_open.values())
        if now - entry["at"] >= SHOWN_AFTER
    ]
    if shown:
        background(get_cache().set(key, shown, KEEP_HELD))
        _published = True
    elif _published:
        background(get_cache().invalidate(key))
        _published = False


def _holding(entry: dict[str, Any]) -> Iterator[FrameType]:
    """Where a holder is now, innermost first: its task's chain of awaits,
    or its thread's stack."""
    if entry["task"] is not None:
        return _awaits(entry["task"])
    return _stack(sys._current_frames().get(entry["thread"]))


async def held() -> list[dict[str, Any]]:
    """Every process's transactions held now, the oldest first."""
    found = await get_cache().values_with_prefix(HELD)
    return sorted(
        (entry for entries in found.values() for entry in entries),
        key=lambda entry: entry["began"],
    )


async def recent() -> list[dict[str, Any]]:
    """What was recorded in the last hour, newest first."""
    found = await get_cache().values_with_prefix(PREFIX)
    return sorted(found.values(), key=lambda e: e["at"], reverse=True)[:SHOWN]


def process() -> str:
    """Which program this is (``python -m app.entrypoints.worker`` is the
    worker; a CLI is its command's name), and its pid."""
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    name = spec.name if spec else Path(sys.argv[0]).stem if sys.argv else ""
    role = name.removesuffix(".__main__").rsplit(".", 1)[-1] or "app"
    return f"{role}:{os.getpid()}"


def _caller(frames: Iterator[FrameType]) -> str:
    """The innermost of ``frames`` in the app's own code."""
    for frame in frames:
        if where := _app_path(frame.f_code.co_filename):
            return f"{where}:{frame.f_lineno} in {frame.f_code.co_name}"
    return "unknown"


@cache
def _app_path(filename: str) -> str | None:
    """``filename`` from the project's root when it is the app's own code
    (not a library's, not the database layer's); resolved once a file, as
    every transaction asks. Code a library generated (``<string>``) is no
    file, though it resolves under the root."""
    if filename.startswith("<"):
        return None
    try:
        where = Path(filename).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return None
    return None if "site-packages" in where or where in DATABASE_LAYER else where


def _frames() -> Iterator[FrameType]:
    """Innermost first: this thread's stack, then the running task's chain
    of awaits. An async session runs its statements in a greenlet whose
    stack stops at SQLAlchemy; the coroutine that asked is on that chain."""
    yield from _stack(sys._getframe(1))
    if (task := _task()) is not None:
        yield from _awaits(task)


def _stack(frame: FrameType | None) -> Iterator[FrameType]:
    while frame is not None:
        yield frame
        frame = frame.f_back


def _awaits(task: asyncio.Task[Any]) -> Iterator[FrameType]:
    """A task's chain of awaits, innermost first."""
    chain: list[FrameType] = []
    awaited: Any = task.get_coro()
    while awaited is not None:
        if found := getattr(awaited, "cr_frame", None):
            chain.append(found)
        awaited = getattr(awaited, "cr_await", None)
    yield from reversed(chain)
