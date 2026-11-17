"""A chat turn as Server-Sent Events: what every chat stream answers with.

The API's ``/chat/stream`` and each chat surface mount's ``/stream`` run
the same turn (``ai_service.stream_chat``) and speak the same frames:
``connect``, a ``chunk`` per delta, a ``tool`` as a tool starts, a
``page`` for an action on the page it is on, ``waiting`` while nothing
arrives (how long, and why where the turn's engine can say), ``final``
with the stored message's ids and metadata, ``complete``; or ``error``.
"""

from collections.abc import AsyncIterator
import json
from typing import Any

from fastapi.responses import StreamingResponse

from app.core.chat_transcript import trail_label
from app.core.concurrency import Waiting, announce_waiting
from app.core.log import logger
from app.core.pages import Page, page_stage
from app.services.ai.service import (
    AIServiceError,
    ConversationError,
    ProviderError,
    StreamingMessage,
    waiting_reason,
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
    frontend can caption the pause. Its trail line rides the notice
    (``trace.tool_notice``) or is read from its arguments here; every chat
    surface shows this label live, and the stored trace renders the same
    words later (``chat_transcript.trace_label``)."""
    tool = str(chunk.metadata.get("tool", ""))
    args = str(chunk.metadata.get("args", "") or "")
    label = str(chunk.metadata.get("label") or trail_label(tool, args))
    return event("tool", {"tool": tool, "args": args, "label": label})


def _waiting(quiet: Waiting) -> str:
    """A quiet stretch, with the words a chat shows for it until the
    answer starts: its reason and how long, else how long alone."""
    seconds = f"{quiet.seconds}s"
    label = f"{quiet.reason} - {seconds}" if quiet.reason else f"waiting {seconds}"
    return event(
        "waiting", {"seconds": quiet.seconds, "reason": quiet.reason, "label": label}
    )


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


async def _events(
    chunks: AsyncIterator[StreamingMessage], page: Page | None = None
) -> AsyncIterator[str]:
    # What the agent does to the page (``page_action``), sent before the
    # frame that follows it.
    acted: list[dict[str, Any]] = []

    async def send(action: dict[str, Any]) -> None:
        acted.append(action)

    # Quiet after a tool's frame is the tool at work, not the model
    # thinking: no reason, and its engine is not asked.
    tool_running = False

    async def why() -> str | None:
        return None if tool_running else await waiting_reason()

    try:
        with page_stage(page, send):
            yield event(
                "connect", {"status": "connected", "message": "Streaming started"}
            )
            async for chunk in announce_waiting(chunks, explain=why):
                if isinstance(chunk, Waiting):
                    yield _waiting(chunk)
                    continue
                for action in acted:
                    yield event("page", action)
                acted.clear()
                tool_running = (chunk.metadata or {}).get("event") == "tool"
                if tool_running:
                    yield _tool(chunk)
                    continue
                yield _chunk(chunk)
                if chunk.is_final:
                    break
        yield event("complete", {"status": "completed", "message": "Stream finished"})
    # Subclasses before AIServiceError, or their branches never run. An
    # error's text is logged, not sent: a provider's or the service's can
    # carry keys or URLs, and the label says enough.
    except ProviderError:
        logger.exception("Chat stream provider error")
        yield event("error", {"error": "AI provider error"})
    except ConversationError:
        logger.warning("Chat stream conversation error", exc_info=True)
        yield event("error", {"error": "Conversation error"})
    except AIServiceError:
        logger.exception("Chat stream service error")
        yield event("error", {"error": "AI service error"})
    except Exception:
        # Logged, not sent: the text can carry paths, keys or SQL.
        logger.exception("Chat stream failed")
        yield event("error", {"error": "Unexpected error"})


def turn_stream(
    chunks: AsyncIterator[StreamingMessage], page: Page | None = None
) -> StreamingResponse:
    """A turn's chunks (``ai_service.stream_chat``) as the SSE response, on
    the page it is on (``app.core.pages``: none, for the API)."""
    return StreamingResponse(
        _events(chunks, page), media_type="text/event-stream", headers=HEADERS
    )


def refused(reason: str) -> StreamingResponse:
    """A turn refused before it reached the model, as its one frame."""

    async def frames() -> AsyncIterator[str]:
        yield event("error", {"error": reason})

    return StreamingResponse(frames(), media_type="text/event-stream", headers=HEADERS)
