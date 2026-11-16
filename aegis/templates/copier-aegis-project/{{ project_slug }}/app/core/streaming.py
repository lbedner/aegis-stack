"""Say how long a stream has been quiet, whatever is producing it.

Between a chat stream's first frame and its first token nothing is sent,
so a local model loading for forty seconds looked exactly like a hang.
Not a heartbeat (one ticks regardless, and a stream that is answering has
nothing to explain): this is silence, named, only while it lasts. It lives
in core over a bare async iterator because going quiet is not a chat
problem; the SSE event a caller sends for one is ``waiting``.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
import contextvars
from dataclasses import dataclass
import time
from typing import TypeVar

T = TypeVar("T")

# Long enough that an answering stream never trips it, short enough that
# a stalled one is named before someone decides the app is broken.
QUIET_SECONDS = 2.0


@dataclass(frozen=True)
class Waiting:
    """``seconds`` of silence since the last item (not since the stream
    opened: a pause mid-answer reports its own length), and why, when the
    caller's explainer could say."""

    seconds: int
    reason: str | None = None


async def announce_waiting(
    source: AsyncIterator[T],
    *,
    every: float = QUIET_SECONDS,
    explain: Callable[[], Awaitable[str | None]] | None = None,
) -> AsyncIterator[T | Waiting]:
    """Pass ``source`` through, yielding a ``Waiting`` every ``every``
    seconds it is quiet. What the source raises is raised here.

    ``explain`` is asked once per quiet stretch, in the source's own
    context (so it reads what the source has set by then, the turn's
    model), and one that fails is no reason: a missing reason must never
    turn a slow answer into a failed one.

    Each step runs as a task, so a timeout ends the wait and not the step;
    every step shares one context, so a ContextVar the source sets while
    producing one item can be reset while producing a later one. Closed
    early (Stop, a closed tab), the step in flight is cancelled with it.
    """
    stepping = source.__aiter__()

    async def step() -> T:
        return await stepping.__anext__()

    async def why() -> str | None:
        return await explain() if explain is not None else None

    context = contextvars.copy_context()
    loop = asyncio.get_running_loop()
    since = time.monotonic()
    pending: asyncio.Task[T] | None = None
    try:
        while True:
            pending = loop.create_task(step(), context=context)
            reason: str | None = None
            asked = False
            while True:
                try:
                    item = await asyncio.wait_for(asyncio.shield(pending), every)
                except TimeoutError:
                    if explain is not None and not asked:
                        asked = True
                        try:
                            reason = await loop.create_task(why(), context=context)
                        except Exception:  # noqa: BLE001 - see the docstring
                            reason = None
                    yield Waiting(seconds=int(time.monotonic() - since), reason=reason)
                    continue
                except StopAsyncIteration:
                    return
                break
            since = time.monotonic()
            yield item
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
