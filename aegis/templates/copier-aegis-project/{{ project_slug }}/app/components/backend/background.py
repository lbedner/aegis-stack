"""The webserver's background loops, started by a startup hook and stopped
by its shutdown hook: one home for keeping and cancelling them."""

import asyncio
from collections.abc import Coroutine
import contextlib
from typing import Any

_tasks: dict[str, asyncio.Task[None]] = {}


def start(name: str, work: Coroutine[Any, Any, None]) -> None:
    """Run ``work`` in the background under ``name``."""
    _tasks[name] = asyncio.create_task(work, name=name)


async def stop(name: str) -> None:
    """Cancel ``name``'s loop and wait for it to end; a no-op if none runs."""
    task = _tasks.pop(name, None)
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
