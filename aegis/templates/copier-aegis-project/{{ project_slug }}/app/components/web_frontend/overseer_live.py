"""One fragment of an Overseer page, pushed over SSE while the page is open.

The page connects when it renders and the stream ends after
``MAX_STREAM_SECONDS`` (the browser reconnects), so nothing samples while
nobody is looking. A frame goes out only when the fragment changed.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
import time

from fastapi import Depends
from fastapi.responses import StreamingResponse

from app.core.db import AsyncSessionLocal
from app.services.auth.deps import get_session_token
from app.services.auth.service import get_current_user_from_token
from app.services.auth.users import UserService

MAX_STREAM_SECONDS = 300


async def authenticate_stream(
    token: str | None = Depends(get_session_token),
) -> None:
    """Check the user and close the DB session before the stream begins."""
    async with AsyncSessionLocal() as session:
        await get_current_user_from_token(token, UserService(session))


def event_stream(events: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
