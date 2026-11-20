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
or their process stops refreshing them. Records go on one list in the
shared cache (Redis when the stack has it, so the webserver sees what the
worker and scheduler recorded; this process's memory otherwise), each with
its container's host and who owns its code, as a log line is owned; kept
for ``DATABASE_ACTIVITY_RETENTION_SECONDS`` and read by window (``recent``,
over ``windows``); ``grouped`` sums them by the code behind them, and
``summary`` is the last hour so, small enough for Illiana's ``health``.
Each is also logged, so a process without an event loop to write the
record from still leaves one.
"""

import asyncio
from collections.abc import Callable, Coroutine, Iterator
from datetime import UTC, datetime
import socket
import sys
import threading
import time
from types import FrameType
from typing import Any
from weakref import WeakKeyDictionary

from sqlalchemy import Engine, event
from sqlalchemy.sql.util import find_tables

from app.core import edges, frames, series
from app.core.cache import get_cache
from app.core.concurrency import background
from app.core.config import settings
from app.core.log import logger
from app.core.log_attribution import owners

KEY = "db_activity"
# ponytail: the newest this many, whatever the retention; a busier week
# loses its oldest first. Each is a few hundred bytes.
KEEP = 5000
# How many of the newest ``recent`` reads first; it reads four times as
# many each time the window reaches further back.
FIRST_READ = 250
# The summary ``health`` carries: the last hour's costliest code sites.
SUMMARY_SECONDS = 3600
SUMMARY_TOP = 8
# The tables each compiled statement touches, worked out once a statement.
_tables_of: WeakKeyDictionary[Any, list[str]] = WeakKeyDictionary()
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
    """Time every transaction on ``engine`` and catch its lock failures;
    count every statement as a hop (``edges``): to the database from the
    code on the stack, and from its innermost part to each table."""
    event.listen(engine, "before_cursor_execute", _statement_began)
    event.listen(engine, "after_cursor_execute", _statement_ran)
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


def _info(conn: Any) -> dict[Any, Any]:
    """``conn.info``, or nothing on a connection a cancelled statement left
    invalid: reading it there raises, and these listeners run inside the
    rollback that cleans it up, so the cancel became that error."""
    return {} if conn is None or conn.invalidated else conn.info


def _ended(conn: Any) -> None:
    began = _info(conn).pop("began_at", None)
    if began is not None and is_slow(held := time.monotonic() - began):
        _record("slow", round(held, 2))


def _failed(context: Any) -> None:
    if "database is locked" in str(context.original_exception):
        _record("locked", None)
    _hop(context.connection, context.execution_context, error=True)


def _statement_began(conn: Any, *_: Any) -> None:
    conn.info["statement_at"] = time.perf_counter()


def _statement_ran(
    conn: Any, _cursor: Any, _sql: str, _params: Any, context: Any, _many: bool
) -> None:
    _hop(conn, context, error=False)


def _hop(conn: Any, context: Any, *, error: bool) -> None:
    started = _info(conn).pop("statement_at", None)
    ms = (time.perf_counter() - started) * 1000 if started else 0.0
    tables = _tables(context)
    chain = edges.hop(edges.DATABASE, ms=ms, error=error, tables=tables)
    for table in tables if chain else ():
        edges.count(chain[-2], f"object:{table}", ms=ms, error=error)


def _tables(context: Any) -> list[str]:
    """The tables a compiled statement reads or writes, by name."""
    compiled = getattr(context, "compiled", None)
    if compiled is None:
        return []
    if (found := _tables_of.get(compiled)) is not None:
        return found
    try:
        touched = find_tables(compiled.statement, include_crud=True, include_joins=True)
    except Exception:  # noqa: BLE001 - text() and the like name no tables
        touched = []
    found = sorted({t.name for t in touched if getattr(t, "name", None)})
    _tables_of[compiled] = found
    return found


def _record(kind: str, seconds: float | None) -> None:
    entry = describe(kind, seconds, frames.process(), _caller(frames.frames()))
    logger.warning("Database activity", **entry)
    try:
        asyncio.get_running_loop()
    except RuntimeError:  # no loop to write from: the log line is the record
        return
    background(store(entry))


def describe(
    kind: str,
    seconds: float | None,
    process: str,
    caller: str,
    at: datetime | None = None,
) -> dict[str, Any]:
    """One record: what, for how long, where (the process and its
    container's host), the code behind it and who owns that code, and when."""
    app_service, app_component = owners(caller.partition(":")[0])
    return {
        "kind": kind,
        "seconds": seconds,
        "process": process,
        "host": HOST,
        "caller": caller,
        "app_service": app_service,
        "app_component": app_component,
        "at": (at or datetime.now(UTC)).isoformat(timespec="seconds"),
    }


def store(entry: dict[str, Any]) -> Coroutine[Any, Any, Any]:
    """Keep a record for the retention, the newest ``KEEP`` of them."""
    keep = settings.DATABASE_ACTIVITY_RETENTION_SECONDS
    return get_cache().push(KEY, entry, KEEP, keep)


def _waits_on_itself(conn: Any) -> None:
    """A task opening a locking transaction while it holds one: SQLite has
    one writer, so it waits out the busy timeout behind itself and fails."""
    task = frames.current_task()
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
        "task": frames.current_task(),
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
    key = f"{HELD}{frames.process()}"
    shown = [
        {
            "process": frames.process(),
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
        return frames.awaits(entry["task"])
    return frames.stack(sys._current_frames().get(entry["thread"]))


async def held() -> list[dict[str, Any]]:
    """Every process's transactions held now, the oldest first."""
    found = await get_cache().values_with_prefix(HELD)
    return sorted(
        (entry for entries in found.values() for entry in entries),
        key=lambda entry: entry["began"],
    )


def windows() -> tuple[tuple[int, str], ...]:
    """The container charts' windows (``series.HISTORY_WINDOWS``) the
    retention keeps."""
    keep = settings.DATABASE_ACTIVITY_RETENTION_SECONDS
    return tuple(w for w in series.HISTORY_WINDOWS if w[0] <= keep)


async def recent(seconds: float) -> list[dict[str, Any]]:
    """What was recorded in the last ``seconds``, newest first: read back
    only as far as the window reaches, as the list keeps a week and health
    asks for the hour."""
    keep = settings.DATABASE_ACTIVITY_RETENTION_SECONDS
    since = datetime.now(UTC).timestamp() - min(seconds, keep)
    newest = FIRST_READ
    while True:
        read = await get_cache().listed(KEY, newest)
        found = [
            e for e in read if datetime.fromisoformat(e["at"]).timestamp() >= since
        ]
        if len(found) < len(read) or len(read) < newest or newest >= KEEP:
            return found
        newest *= 4


def grouped(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``events`` by the code behind them, the longest held in all first:
    how many, the seconds held in all and at most, the latest, and the
    kinds and processes (by name, not pid) among them."""
    by_code: dict[str, list[dict[str, Any]]] = {}
    for entry in events:
        by_code.setdefault(entry["caller"], []).append(entry)
    groups = [
        {
            "code": code,
            "count": len(found),
            "held_s": round(sum(e["seconds"] or 0 for e in found), 2),
            "longest_s": max((e["seconds"] or 0 for e in found), default=0),
            "last": max(e["at"] for e in found),
            "kinds": sorted({e["kind"] for e in found}),
            "processes": sorted({frames.role_of(e["process"]) for e in found}),
        }
        for code, found in by_code.items()
    ]
    return sorted(groups, key=lambda g: (-g["held_s"], -g["count"], g["code"]))


async def summary() -> dict[str, Any]:
    """The last hour by code, its costliest ``SUMMARY_TOP``: what the
    database health carries, so Illiana reads it whole however busy."""
    groups = grouped(await recent(SUMMARY_SECONDS))
    return {
        "window_s": SUMMARY_SECONDS,
        "slow_after_s": settings.DATABASE_SLOW_TRANSACTION_SECONDS,
        "code_sites": len(groups),
        "by_code": groups[:SUMMARY_TOP],
    }


def _caller(frames: Iterator[FrameType]) -> str:
    """The innermost of ``frames`` in the app's own code."""
    for frame in frames:
        if where := _app_path(frame.f_code.co_filename):
            return f"{where}:{frame.f_lineno} in {frame.f_code.co_name}"
    return "unknown"


def _app_path(filename: str) -> str | None:
    """``filename`` from the project's root when it is the app's own code
    and not the database layer's."""
    where = frames.app_path(filename)
    return None if where in DATABASE_LAYER else where
