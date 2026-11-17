"""A live call's finished turn, kept in its conversation as a typed turn
is kept (``realtime_calls.drive`` saves each one)."""

from __future__ import annotations

from typing import Any

from app.services.ai.models import MessageRole


async def save_turn(
    ai: Any,
    conversation_id: str,
    heard: str,
    said: str,
    trace: list[dict[str, Any]],
    *,
    model: str,
    provider: str,
    usage: dict[str, Any] | None = None,
    interrupted: bool = False,
) -> None:
    """The turn into the conversation, as a typed turn is kept: ``usage``
    is its share of the call (tokens and cost), for its footer. A turn the
    call dropped in the middle of is ``interrupted``, and keeps what was
    asked so the next call can pick it up (``resumed``)."""
    conversation = await ai.get_conversation(conversation_id)
    if conversation is None:
        return
    if heard:
        conversation.add_message(MessageRole.USER, heard)
    metadata: dict[str, Any] = {
        "conversation_id": conversation_id,
        "provider": provider,
        "model": model,
        "stream_complete": True,
    }
    if trace:
        metadata["tool_trace"] = trace
    metadata.update(usage or {})
    if interrupted:
        metadata.update(interrupted=True, asked=heard)
    conversation.add_message(MessageRole.ASSISTANT, said, metadata=metadata)
    await ai.conversation_manager.save_conversation(conversation)
