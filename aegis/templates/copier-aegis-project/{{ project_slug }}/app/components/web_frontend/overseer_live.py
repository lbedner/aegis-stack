"""One fragment of an Overseer page, pushed over SSE while the page is open.

The page connects when it renders and the stream ends after
``MAX_STREAM_SECONDS`` (the browser reconnects), so nothing samples while
nobody is looking. A frame goes out only when the fragment changed.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
import contextlib
import time
from typing import Any

from fastapi.responses import StreamingResponse

from app.core import series
from app.core.log import logger

from .rendering import templates, with_query

MAX_STREAM_SECONDS = 300
MACROS = "components/macros/layout.html"  # ``chart_data``, a chart's data
# A comment line this often keeps a quiet pushed stream (``heartbeat``) open,
# and finds a closed tab.
HEARTBEAT_SECONDS = 15.0


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
    its html differs from the last one sent. A ``render()`` that fails
    sends nothing that round: the page keeps what it shows."""
    last: dict[str, str] = {}
    deadline = time.monotonic() + MAX_STREAM_SECONDS
    frames = 0
    while time.monotonic() < deadline and (max_frames is None or frames < max_frames):
        frames += 1
        try:
            sent = changed_frames(last, await render())
        except Exception as exc:  # noqa: BLE001 - one bad read, not the stream's end
            logger.warning("Overseer stream read failed", error=str(exc))
            sent = []
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
        frames.append(frame(event, html))
    return frames


def frame(event: str, html: str) -> str:
    """One htmx SSE frame: ``html``, on one line, as ``event``."""
    data = html.strip().replace("\r", "").replace("\n", " ")
    return f"event: {event}\ndata: {data}\n\n"


async def heartbeat(
    frames: AsyncIterator[str], every: float = HEARTBEAT_SECONDS
) -> AsyncIterator[str]:
    """``frames`` (a stream something pushes, not one polled) with a comment
    whenever none comes for ``every`` seconds, so a closed tab is noticed;
    ended after ``MAX_STREAM_SECONDS`` like every other stream."""
    deadline = time.monotonic() + MAX_STREAM_SECONDS
    upcoming = asyncio.ensure_future(anext(frames))
    try:
        while time.monotonic() < deadline:
            done, _ = await asyncio.wait({upcoming}, timeout=every)
            if not done:
                yield ": heartbeat\n\n"
                continue
            try:
                yield upcoming.result()
            except StopAsyncIteration:
                return
            upcoming = asyncio.ensure_future(anext(frames))
    finally:
        # The pending read is cancelled and finished before the stream is
        # closed: an async generator cannot close mid-read.
        upcoming.cancel()
        with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
            await upcoming
        await frames.aclose()  # type: ignore[attr-defined]


def chart_panel(
    prefix: str, charts: list[dict[str, Any]], seconds: int, events: str
) -> dict[str, Any]:
    """A page's live charts as its ``live_charts`` macro draws them: each
    chart with its id (``prefix``-key, its stream event too), the range
    chips over ``seconds``, and the stream (``events``) over that window."""
    return {
        "charts": [chart | {"id": f"{prefix}-{chart['key']}"} for chart in charts],
        "windows": series.WINDOWS,
        "window": seconds,
        "events": with_query(events, window=str(seconds)),
    }


def chart_frames(
    prefix: str,
    charts: list[dict[str, Any]],
    held: dict[str, tuple[list[str], int]],
) -> dict[str, str]:
    """Each chart's frame for a live stream, by its event (``chart_panel``'s
    id): whole at first and when its lines change, and after that only its
    new points (``series.since``). ``held``: each chart's lines and the
    newest time sent, which the page now has; kept across frames."""
    chart_data = templates.env.get_template(MACROS).module.chart_data  # type: ignore[attr-defined]
    sent = {}
    for chart in charts:
        event, data = f"{prefix}-{chart['key']}", chart["data"]
        lines = [line["label"] for line in data["series"]]
        if event in held and held[event][0] == lines:
            data = series.since(data, held[event][1])
        if data["labels"]:
            held[event] = (lines, data["labels"][-1])
        sent[event] = str(chart_data(event, data))
    return sent
