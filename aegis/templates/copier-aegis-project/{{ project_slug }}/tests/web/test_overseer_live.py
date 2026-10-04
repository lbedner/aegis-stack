"""The Overseer's live streams (``overseer_live``): the frame encoding every
stream shares, and the heartbeat a pushed stream (Logs) rides on."""

import asyncio
from collections.abc import AsyncIterator

from app.components.web_frontend import overseer_live


def test_a_frame_is_one_line_of_html_under_its_event() -> None:
    assert overseer_live.frame("logs-lines", "<tr>\n<td>a</td>\n</tr>\n") == (
        "event: logs-lines\ndata: <tr> <td>a</td> </tr>\n\n"
    )


async def _quiet() -> AsyncIterator[str]:
    """A stream with nothing to say yet (no new log lines)."""
    await asyncio.sleep(3600)
    yield "never"


async def test_a_quiet_stream_gets_heartbeats_and_closes_cleanly() -> None:
    """A tab closing mid-wait closes the stream without an error (its
    pending read is cancelled first)."""
    stream = overseer_live.heartbeat(_quiet(), every=0.01)
    assert await anext(stream) == ": heartbeat\n\n"
    await stream.aclose()  # type: ignore[attr-defined]


async def test_a_stream_passes_its_frames_through_and_ends() -> None:
    async def two() -> AsyncIterator[str]:
        yield "a"
        yield "b"

    assert [f async for f in overseer_live.heartbeat(two(), every=5)] == ["a", "b"]
