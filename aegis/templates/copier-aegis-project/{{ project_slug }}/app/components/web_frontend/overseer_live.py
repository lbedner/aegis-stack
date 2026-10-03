"""One fragment of an Overseer page, pushed over SSE while the page is open.

The page connects when it renders and the stream ends after
``MAX_STREAM_SECONDS`` (the browser reconnects), so nothing samples while
nobody is looking. A frame goes out only when the fragment changed.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
import time

from fastapi.responses import StreamingResponse

MAX_STREAM_SECONDS = 300


def event_stream(events: AsyncIterator[str]) -> StreamingResponse:
    """An SSE response. Who may open one is the Overseer gate's call
    (``overseer_access``), as for every Overseer route."""
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def fragment_events(
    event: str,
    render: Callable[[], Awaitable[str]],
    interval: float,
    max_frames: int | None = None,
) -> AsyncIterator[str]:
    """``render()`` every ``interval`` seconds, sent as ``event`` in the htmx
    SSE format when it differs from the last one sent."""

    async def one() -> dict[str, str]:
        return {event: await render()}

    return fragments_events(one, interval, max_frames)


async def fragments_events(
    render: Callable[[], Awaitable[dict[str, str]]],
    interval: float,
    max_frames: int | None = None,
) -> AsyncIterator[str]:
    """Several fragments on one stream (a table and its charts, say):
    ``render()`` gives html by event name, and each event goes out when
    its html differs from the last one sent."""
    last: dict[str, str] = {}
    deadline = time.monotonic() + MAX_STREAM_SECONDS
    frames = 0
    while time.monotonic() < deadline and (max_frames is None or frames < max_frames):
        frames += 1
        sent = changed_frames(last, await render())
        for frame in sent:
            yield frame
        if not sent:
            yield ": unchanged\n\n"
        await asyncio.sleep(interval)


def changed_frames(last: dict[str, str], payloads: dict[str, str]) -> list[str]:
    """The htmx SSE frames for the events whose html differs from ``last``
    (the html last sent for each), which it brings up to date."""
    frames = []
    for event, html in payloads.items():
        if last.get(event) == html:
            continue
        last[event] = html
        data = html.strip().replace("\r", "").replace("\n", " ")
        frames.append(f"event: {event}\ndata: {data}\n\n")
    return frames
