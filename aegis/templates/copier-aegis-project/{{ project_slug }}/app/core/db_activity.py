"""Database activity worth a look: a transaction held longer than
``DATABASE_SLOW_TRANSACTION_SECONDS``, and a statement that found the
database locked, each with the process and the app code behind it.

SQLite keeps no record of who held its lock, so a "database is locked"
failure used to be guessed at from timestamps. ``watch`` times every
transaction on an engine and catches lock failures; ``recent`` reads what
was recorded, for the Database pages. Records go through the shared cache
(Redis when the stack has it, so the webserver sees what the worker and
scheduler recorded; this process's memory otherwise) and expire after an
hour. Each is also logged, so a process without an event loop to write the
record from still leaves one.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
import os
from pathlib import Path
import sys
import time
from types import FrameType
from typing import Any
import uuid

from sqlalchemy import Engine, event

from app.core.cache import get_cache
from app.core.config import settings
from app.core.log import logger

PREFIX = "db_activity:"
KEEP_SECONDS = 3600
SHOWN = 50
# The project root: a caller is the innermost frame in the app's own code.
ROOT = Path(__file__).resolve().parents[2]
DATABASE_LAYER = ("app/core/db.py", "app/core/db_activity.py")
# Record writes in flight, held so they are not collected before they run.
_writes: set[asyncio.Task[None]] = set()


def watch(engine: Engine) -> None:
    """Time every transaction on ``engine`` and catch its lock failures."""
    event.listen(engine, "begin", _began)
    event.listen(engine, "commit", _ended)
    event.listen(engine, "rollback", _ended)
    event.listen(engine, "handle_error", _failed)


def _began(conn: Any) -> None:
    conn.info["began_at"] = time.monotonic()


def _ended(conn: Any) -> None:
    began = conn.info.pop("began_at", None)
    limit = settings.DATABASE_SLOW_TRANSACTION_SECONDS
    if began is not None and limit and (held := time.monotonic() - began) >= limit:
        _record("slow", round(held, 2))


def _failed(context: Any) -> None:
    if "database is locked" in str(context.original_exception):
        _record("locked", None)


def _record(kind: str, seconds: float | None) -> None:
    entry = {
        "kind": kind,
        "seconds": seconds,
        "process": _process(),
        "caller": _caller(),
        "at": datetime.now(UTC).isoformat(),
    }
    logger.warning("Database activity", **entry)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # no loop to write from: the log line is the record
        return
    key = f"{PREFIX}{entry['at']}:{uuid.uuid4().hex[:8]}"
    write = loop.create_task(get_cache().set(key, entry, KEEP_SECONDS))
    _writes.add(write)
    write.add_done_callback(_writes.discard)


async def recent() -> list[dict[str, Any]]:
    """What was recorded in the last hour, newest first."""
    found = await get_cache().values_with_prefix(PREFIX)
    return sorted(found.values(), key=lambda e: e["at"], reverse=True)[:SHOWN]


def _process() -> str:
    """Which program this is (``python -m app.entrypoints.worker`` is the
    worker; a CLI is its command's name), and its pid."""
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    name = spec.name if spec else Path(sys.argv[0]).stem if sys.argv else ""
    role = name.removesuffix(".__main__").rsplit(".", 1)[-1] or "app"
    return f"{role}:{os.getpid()}"


def _caller() -> str:
    """The innermost frame of the app's own code that led here."""
    for frame in _frames():
        try:
            path = Path(frame.f_code.co_filename).resolve().relative_to(ROOT)
        except ValueError:
            continue
        where = path.as_posix()
        if "site-packages" in where or where in DATABASE_LAYER:
            continue
        return f"{where}:{frame.f_lineno} in {frame.f_code.co_name}"
    return "unknown"


def _frames() -> Iterator[FrameType]:
    """Innermost first: this thread's stack, then the running task's chain
    of awaits. An async session runs its statements in a greenlet whose
    stack stops at SQLAlchemy; the coroutine that asked is on that chain."""
    frame: FrameType | None = sys._getframe(1)
    while frame is not None:
        yield frame
        frame = frame.f_back
    try:
        task = asyncio.current_task()
    except RuntimeError:
        return
    chain: list[FrameType] = []
    awaited: Any = task.get_coro() if task else None
    while awaited is not None:
        if found := getattr(awaited, "cr_frame", None):
            chain.append(found)
        awaited = getattr(awaited, "cr_await", None)
    yield from reversed(chain)
