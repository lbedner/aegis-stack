"""Where code is running: this thread's stack and the greenlets it was
switched from, innermost first (a task's chain of awaits, for another
task), and which of their files are the app's own.
What a record says came from where (``db_activity``'s callers, ``edges``'
hops) is read from here."""

import asyncio
from collections.abc import Iterator
from functools import cache
import os
from pathlib import Path
import sys
from types import FrameType
from typing import Any

from app.core.source_index import ROOT


def current_task() -> asyncio.Task[Any] | None:
    try:
        return asyncio.current_task()
    except RuntimeError:  # a thread with no loop: a sync session's
        return None


def frames() -> Iterator[FrameType]:
    """Innermost first: this thread's stack, then the stacks of the
    greenlets it was switched from. An async session runs its statements
    in a greenlet whose stack stops at SQLAlchemy; the code that awaited it
    waits in the greenlet that switched to it, still running. A running
    task's own chain of awaits is on the stack already (``awaits`` reads
    another task's)."""
    yield from stack(sys._getframe(1))
    yield from switched_from()


def switched_from() -> Iterator[FrameType]:
    """The stacks of the greenlets this one was switched to from, nearest
    first; none outside a greenlet (or where greenlet is not installed:
    then nothing runs in one)."""
    greenlet = sys.modules.get("greenlet")
    parent = greenlet.getcurrent().parent if greenlet else None
    while parent is not None:
        yield from stack(parent.gr_frame)
        parent = parent.parent


def stack(frame: FrameType | None) -> Iterator[FrameType]:
    while frame is not None:
        yield frame
        frame = frame.f_back


def awaits(task: asyncio.Task[Any]) -> Iterator[FrameType]:
    """A task's chain of awaits, innermost first."""
    chain: list[FrameType] = []
    awaited: Any = task.get_coro()
    while awaited is not None:
        if found := getattr(awaited, "cr_frame", None):
            chain.append(found)
        awaited = getattr(awaited, "cr_await", None)
    yield from reversed(chain)


def process() -> str:
    """Which program this is (``python -m app.entrypoints.worker`` is the
    worker; a CLI is its command's name), and its pid."""
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    name = spec.name if spec else Path(sys.argv[0]).stem if sys.argv else ""
    role = name.removesuffix(".__main__").rsplit(".", 1)[-1] or "app"
    return f"{role}:{os.getpid()}"


@cache
def app_path(filename: str) -> str | None:
    """``filename`` from the project's root when it is the app's own code,
    not a library's; resolved once a file, as every record asks. Code a
    library generated (``<string>``) is no file, though it resolves under
    the root."""
    if filename.startswith("<"):
        return None
    try:
        where = Path(filename).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return None
    return None if "site-packages" in where or ".venv/" in where else where
