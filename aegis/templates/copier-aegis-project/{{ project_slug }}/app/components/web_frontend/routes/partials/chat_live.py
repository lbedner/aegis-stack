"""A live call from the chat surface, on any mount: one path for every
engine.

The page opens a WebSocket here; the server opens the engine's realtime
session (the key never leaves it) and carries the audio both ways: the
microphone arrives as binary frames (PCM16 at the model's input rate) and
the voice goes back the same way (at its output rate), while a few JSON
events tell the page what the call is doing. ``realtime_calls.drive`` does
the rest: the agent's tools, the saved turns, the priced usage.

``live_router(mount, socket_guard)`` builds it under the mount's path,
behind a guard a socket can run (it carries cookies, never a bearer
header). It is its own router, apart from the mount's pages: a page guard
reads an HTTP request a socket does not have.
"""

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, WebSocket
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    PartEndEvent,
    RealtimeResponseInterruptedEvent,
    RealtimeTurnCompleteEvent,
    SpeechPart,
)

from app.components.backend.api.ai.service import ai_service
from app.components.web_frontend import chat_surface as chat
from app.components.web_frontend.chat_surface import ChatSurface
from app.core.chat_transcript import trace_label
from app.core.config import settings
from app.core.db import get_async_session
from app.core.log import logger
from app.services.ai.domains.voice import live_engines, realtime_calls
from app.services.ai.models import AIProvider
from app.services.ai.models.voice import LiveEngine
from app.services.ai.service.trace import record_tool_call

# Sent the moment the call is up, so the assistant speaks first: a cue
# rather than a line, so the greeting varies.
GREETING = (
    "The call just connected. Greet them warmly in a few words and ask "
    "what they would like to talk about."
)
# A call into a conversation already under way: no introductions.
CONTINUING = (
    "The call just connected, in a conversation you are already having with "
    "them (it is above). Greet them briefly as someone you know - no "
    "introductions - and ask what is next."
)
# A call soon after one dropped mid-answer picks it up.
RESUMING = (
    "The call just reconnected. It dropped while you were answering them; "
    'they had asked: "{asked}". Say in a few words that you got cut off, '
    "then pick that answer up."
)


def opening(conversation: Any) -> str:
    """How the call opens: picking up a dropped one, carrying on a
    conversation, or a first greeting."""
    if conversation is None:
        return GREETING
    if asked := realtime_calls.resumed(conversation):
        return RESUMING.format(asked=asked)
    return CONTINUING if conversation.messages else GREETING


async def _engine_now() -> tuple[LiveEngine | None, dict[str, Any] | None]:
    """The engine the voice profile names, and what the call bar shows of
    it. Its own short session: a call writes in others."""
    async with get_async_session() as db:
        engine = await live_engines.resolve(db, settings.VOICE_LIVE_ENGINE)
        info = engine and {"label": engine.llm.title}
    return engine, info


async def _send(ws: WebSocket, message: dict[str, Any]) -> None:
    try:
        await ws.send_json(message)
    except Exception:  # the page hung up first
        return


async def _tell(ws: WebSocket, event: Any) -> None:
    """What the page shows of an event, if anything."""
    said: dict[str, Any] | None = None
    if isinstance(event, RealtimeResponseInterruptedEvent):
        said = {"type": "interrupted"}  # drop what has not been played
    elif isinstance(event, FunctionToolCallEvent):
        if event.part.tool_name == realtime_calls.END_CALL:
            said = {"type": "hang_up"}  # after the goodbye has played
        else:
            step: list[dict[str, Any]] = []
            record_tool_call(step, event)
            said = {"type": "working", "label": trace_label(step[0])}
    elif isinstance(event, RealtimeTurnCompleteEvent):
        said = {"type": "done"}
    elif isinstance(event, PartEndEvent) and isinstance(event.part, SpeechPart):
        side = "heard" if event.part.speaker == "user" else "said"
        said = {"type": side, "text": event.part.transcript or ""}
    if said:
        await _send(ws, said)


async def _carry(
    ws: WebSocket, session: Any, conversation: Any, info: dict[str, Any] | None
) -> None:
    """The audio, both ways, until the page hangs up."""
    await ws.send_json(
        {
            "type": "ready",
            "input_rate": session.audio_input_sample_rate,
            "output_rate": session.audio_output_sample_rate,
            "conversation_id": conversation.id,
            "engine": info,
        }
    )

    async def speak() -> None:
        async for chunk in session.stream_audio():
            await ws.send_bytes(chunk)

    voice = asyncio.create_task(speak())
    try:
        await session.send(opening(conversation))
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes"):
                await session.send_audio(message["bytes"])
    finally:
        voice.cancel()
        await session.close()


def live_router(mount: ChatSurface, socket_guard: Callable[..., Any]) -> APIRouter:
    """The call's socket, under ``mount.path``/live/ws, behind
    ``socket_guard``."""
    router = APIRouter(prefix=mount.path, dependencies=[Depends(socket_guard)])
    agent_slug = mount.voice_agent_slug or mount.agent_slug

    async def call_for(conversation_id: str | None, engine: LiveEngine) -> Any:
        """The conversation the call saves into (a call without one starts
        one) and the agent as the engine's brain."""
        model = live_engines.realtime_model(engine)
        conversation = (
            await chat.find_conversation(mount, conversation_id)
            if conversation_id
            else await ai_service.conversation_manager.create_conversation(
                provider=AIProvider(engine.llm.served_by.slug),
                model=model,
                user_id=mount.user,
                surface=mount.surface,
            )
        )
        if conversation is None:
            raise LookupError("not this mount's conversation")
        realtime = await realtime_calls.realtime_for(
            ai_service,
            conversation=conversation,
            model=model,
            agent_slug=agent_slug,
            voice=settings.TTS_VOICE,
            instructions=engine.instructions,
            max_output_tokens=engine.max_output_tokens,
        )
        return conversation, realtime

    async def show_cards(ws: WebSocket, card_ids: list[str]) -> None:
        """A card drawn mid-call, up while it is talked about."""
        for card_id in card_ids:
            await _send(ws, {"type": "card", "url": f"{mount.path}/cards/{card_id}"})

    @router.websocket("/live/ws")
    async def live_call(ws: WebSocket, conversation_id: str | None = None) -> None:
        """A call, for as long as the page holds the socket."""
        await ws.accept()
        engine, info = await _engine_now()
        if engine is None:
            await ws.close(code=1008, reason="No live engine is enabled.")
            return
        try:
            conversation, realtime = await call_for(conversation_id, engine)
        except Exception:
            logger.exception("Opening a live call failed")
            await ws.close(code=1011)
            return
        await realtime_calls.drive(
            ai_service,
            realtime,
            alongside=lambda session: _carry(ws, session, conversation, info),
            on_event=lambda event: _tell(ws, event),
            on_saved=lambda cost: _send(ws, {"type": "saved", "cost": cost}),
            on_drawn=lambda card_ids: show_cards(ws, card_ids),
            conversation_id=conversation.id,
            model=live_engines.realtime_model(engine),
            agent_slug=agent_slug,
            user_id=mount.user,
        )
        try:
            await ws.close()
        except Exception:  # already closed by the page
            return

    return router
