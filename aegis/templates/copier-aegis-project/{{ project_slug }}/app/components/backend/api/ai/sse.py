"""A chat turn as Server-Sent Events: what every chat stream answers with.

The API's ``/chat/stream`` and each chat surface mount's ``/stream`` run
the same turn (``ai_service.stream_chat``) and speak the same frames:
``connect``, a ``chunk`` per delta, a ``tool`` as a tool starts, ``final``
with the stored message's ids and metadata, ``complete``; or ``error``.
"""

from collections.abc import AsyncIterator
import json
from typing import Any

from fastapi.responses import StreamingResponse

from app.core.chat_transcript import tool_label
from app.core.log import logger
from app.services.ai.models import StreamingMessage
from app.services.ai.service import (
    AIServiceError,
    ConversationError,
    ProviderError,
)

HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
}


def event(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def _tool(chunk: StreamingMessage) -> str:
    """A tool-use notice: no content, just which tool started, so the
    frontend can caption the pause. The trail line is computed here, once:
    the browser shows this label live and the stored trace renders the
    same words later (``chat_transcript.trace_label``)."""
    tool = str(chunk.metadata.get("tool", ""))
    args = str(chunk.metadata.get("args", "") or "")
    return event("tool", {"tool": tool, "args": args, "label": tool_label(tool, args)})


def _chunk(chunk: StreamingMessage) -> str:
    data = {
        "content": chunk.content,
        "is_final": chunk.is_final,
        "is_delta": chunk.is_delta,
        "message_id": chunk.message_id,
        "conversation_id": chunk.conversation_id,
        "timestamp": chunk.timestamp.isoformat(),
    }
    if chunk.is_final:
        data.update(chunk.metadata)
    return event("final" if chunk.is_final else "chunk", data)


async def _events(chunks: AsyncIterator[StreamingMessage]) -> AsyncIterator[str]:
    try:
        yield event("connect", {"status": "connected", "message": "Streaming started"})
        async for chunk in chunks:
            if (chunk.metadata or {}).get("event") == "tool":
                yield _tool(chunk)
                continue
            yield _chunk(chunk)
            if chunk.is_final:
                break
        yield event("complete", {"status": "completed", "message": "Stream finished"})
    # Subclasses before AIServiceError, or their branches never run. A
    # provider's or the service's text is logged, not sent: it can carry
    # keys or URLs. Only a conversation error's text is the caller's.
    except ProviderError:
        logger.exception("Chat stream provider error")
        yield event("error", {"error": "AI provider error"})
    except ConversationError as e:
        yield event("error", {"error": "Conversation error", "detail": str(e)})
    except AIServiceError:
        logger.exception("Chat stream service error")
        yield event("error", {"error": "AI service error"})
    except Exception:
        # Logged, not sent: the text can carry paths, keys or SQL.
        logger.exception("Chat stream failed")
        yield event("error", {"error": "Unexpected error"})


def turn_stream(chunks: AsyncIterator[StreamingMessage]) -> StreamingResponse:
    """A turn's chunks (``ai_service.stream_chat``) as the SSE response."""
    return StreamingResponse(
        _events(chunks), media_type="text/event-stream", headers=HEADERS
    )


def refused(reason: str) -> StreamingResponse:
    """A turn refused before it reached the model, as its one frame."""

    async def frames() -> AsyncIterator[str]:
        yield event("error", {"error": reason})

    return StreamingResponse(frames(), media_type="text/event-stream", headers=HEADERS)
