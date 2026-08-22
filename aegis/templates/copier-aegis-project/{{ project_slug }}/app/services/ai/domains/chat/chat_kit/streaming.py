"""NDJSON serialization for chat frames — the streaming-endpoint pattern.

GENERIC. Chat needs a POST body (the message), so the transport is
``fetch`` + a streamed response body rather than ``EventSource`` (GET-only).
The wire format is newline-delimited JSON: one frame object per line, which a
browser reads incrementally from a ``ReadableStream`` and the CLI reads with a
plain line loop.

``ndjson_response`` turns any async iterator of frames into a Starlette
``StreamingResponse`` with the right media type and buffering-off headers.
Policy wires this behind its own auth + gate; the helper is transport only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import json

from starlette.responses import StreamingResponse

from .models import StreamFrame


def ndjson_line(frame: StreamFrame) -> str:
    """One frame as a single NDJSON line (compact, newline-terminated)."""
    return json.dumps(frame.to_dict(), separators=(",", ":"), ensure_ascii=False) + "\n"


async def ndjson_lines(frames: AsyncIterator[StreamFrame]) -> AsyncIterator[str]:
    """Adapt a frame stream to an NDJSON text stream."""
    async for frame in frames:
        yield ndjson_line(frame)


def ndjson_response(frames: AsyncIterator[StreamFrame]) -> StreamingResponse:
    """Wrap a frame stream as a streamed NDJSON HTTP response.

    ``X-Accel-Buffering: no`` and ``Cache-Control: no-cache`` keep proxies
    from buffering the stream, so deltas reach the browser as they are
    produced rather than in one flush at the end.
    """
    return StreamingResponse(
        ndjson_lines(frames),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
