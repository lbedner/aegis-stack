"""One fragment of an Overseer page, pushed over SSE while the page is open.

The page connects when it renders and the stream ends after
``MAX_STREAM_SECONDS`` (the browser reconnects), so nothing samples while
nobody is looking. A frame goes out only when the fragment changed.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
import time

MAX_STREAM_SECONDS = 300


async def fragment_events(
    event: str,
    render: Callable[[], Awaitable[str]],
    interval: float,
    max_frames: int | None = None,
) -> AsyncIterator[str]:
    """``render()`` every ``interval`` seconds, sent as ``event`` in the htmx
    SSE format when it differs from the last one sent."""
    last = ""
    deadline = time.monotonic() + MAX_STREAM_SECONDS
    frames = 0
    while time.monotonic() < deadline and (max_frames is None or frames < max_frames):
        frames += 1
        html = await render()
        if html != last:
            last = html
            data = html.strip().replace("\r", "").replace("\n", " ")
            yield f"event: {event}\ndata: {data}\n\n"
        else:
            yield ": unchanged\n\n"
        await asyncio.sleep(interval)
