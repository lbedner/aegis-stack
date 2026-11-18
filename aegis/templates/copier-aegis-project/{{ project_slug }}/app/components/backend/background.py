"""The webserver's background loops, started by a startup hook and stopped
by its shutdown hook: one home for keeping and cancelling them."""

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
import contextlib
from typing import Any

from app.core.log import logger

_tasks: dict[str, asyncio.Task[None]] = {}


def start(name: str, work: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
    """Run ``work`` in the background under ``name``; its task, to wait on."""
    _tasks[name] = asyncio.create_task(work, name=name)
    return _tasks[name]


async def stop(name: str) -> None:
    """Cancel ``name``'s loop and wait for it to end; a no-op if none runs."""
    task = _tasks.pop(name, None)
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def sweep_every(
    seconds: float,
    sweep: Callable[[Any], Awaitable[int]],
    opened: Callable[[], contextlib.AbstractAsyncContextManager[Any]],
    what: str,
) -> None:
    """Run ``sweep`` every ``seconds``, first that long after it starts, each
    time on a session of its own (``opened``), saying how many ``what`` it
    marked failed. A check that fails (a table a migration has not made
    yet, a database out of reach) is said and tried again next time: the
    sweep ends only when it is stopped."""
    while True:
        await asyncio.sleep(seconds)
        try:
            async with opened() as session:
                count = await sweep(session)
        except Exception as e:
            logger.warning(f"No check for {what}: {e}")
            continue
        if count:
            logger.info(f"Marked {count} {what} failed")
