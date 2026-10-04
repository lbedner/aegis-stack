"""A live call: one path for every engine.

The realtime model IS the brain: the voice agent's prompt, tools and code
mode, built exactly as a turn builds it. The app's server holds the
provider session (the key never leaves it) and the page carries the audio
over the app's own WebSocket (``routes/partials/chat_live.py``). ``drive``
runs the agent's tools in a turn's context, saves each finished turn into
the conversation (what was heard, what was said, the steps - so the thread
shows it like a typed turn), and ledgers the priced usage when it ends.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartEndEvent,
    RealtimeTurnCompleteEvent,
    SpeechPart,
)
from pydantic_ai.toolsets import FunctionToolset

from app.core.log import logger
from app.services.ai import usage_recording
from app.services.ai.domains.chat.cards import attach_cards, card_stage
from app.services.ai.domains.chat.readings import reading_stage
from app.services.ai.domains.chat.user_memory import memory_user
from app.services.ai.domains.voice.live_engines import is_gpt_live
from app.services.ai.models import MessageRole
from app.services.ai.service.trace import record_tool_call, record_tool_result

# What OpenAI transcribes the caller's side with: a saved turn needs both
# sides, and only OpenAI's realtime models need asking.
INPUT_TRANSCRIPTION = "gpt-4o-mini-transcribe"
# OpenAI's voice when the profile names none: its recommended one.
OPENAI_VOICE = "marin"
# How long a dropped call stays one to pick up: a call within this of the
# cut resumes it; after, it is a new call. The conversation is the memory;
# this is only its age.
RESUME_WINDOW = timedelta(minutes=15)


def end_call() -> str:
    """End the call. Use it once they are done - a goodbye, "that's all",
    thanks with nothing more to ask - right after your short goodbye, and
    say nothing after it."""
    return "The call ends when your goodbye has played. Say nothing more."


# A call ends on the agent's tool, not on a phrase the page listens for: a
# model can drop a phrase. The page hangs up when it sees the call.
END_CALL = end_call.__name__
CALL_TOOLS = FunctionToolset([end_call])


class TurnLog:
    """One turn, gathered from the session's events: what was heard, what
    was said, and the steps, recorded as a streamed turn records them."""

    def __init__(self) -> None:
        self._reset()
        # The cards the last event's step drew, for the page at once.
        self.shown: list[str] = []

    def _reset(self) -> None:
        self.heard: list[str] = []
        self.said: list[str] = []
        self.trace: list[dict[str, Any]] = []
        self.drawn: list[dict[str, Any]] = []

    def observe(self, event: Any) -> bool:
        """Take in one event; True when it finished a turn. Ending the call
        is how it ends, not one of the steps."""
        self.shown = []
        if (
            isinstance(event, FunctionToolCallEvent | FunctionToolResultEvent)
            and event.part.tool_name == END_CALL
        ):
            return False
        if isinstance(event, PartEndEvent) and isinstance(event.part, SpeechPart):
            text = (event.part.transcript or "").strip()
            side = self.heard if event.part.speaker == "user" else self.said
            # The same part reported finished twice is not more speech.
            if text and (not side or side[-1] != text):
                side.append(text)
        elif isinstance(event, FunctionToolCallEvent):
            record_tool_call(self.trace, event)
        elif isinstance(event, FunctionToolResultEvent):
            record_tool_result(self.trace, event)
            self.shown = [marker["id"] for marker in self.drawn]
            attach_cards(self.trace, self.drawn)
        return isinstance(event, RealtimeTurnCompleteEvent)

    def take(self) -> tuple[str, str, list[dict[str, Any]]] | None:
        """The finished turn, once; None when nothing was said."""
        heard, said, trace = " ".join(self.heard), " ".join(self.said), self.trace
        self._reset()
        if not heard and not said:
            return None
        return heard, said, trace


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


def _model_settings(
    model: str,
    voice: str | None,
    max_output_tokens: int | None,
    instructions: str | None = None,
) -> dict[str, Any]:
    """The session's settings for its provider. OpenAI transcribes the
    caller only when asked and speaks the profile's voice; Gemini
    transcribes by default and speaks its own."""
    # ponytail: Gemini's default voice; the engine row carries a voice
    # (Kore, Puck, ...) once voices are picked per engine.
    settings: dict[str, Any] = {}
    if model.startswith("openai:"):
        settings["openai_voice"] = voice or OPENAI_VOICE
        if is_gpt_live(model):
            # GPT-Live takes the call manners as its own instructions; the
            # agent's prompt is the backend's. It has no token limit and
            # transcribes itself.
            if instructions:
                settings["openai_live_instructions"] = instructions
            return settings
        settings["input_transcription_model"] = INPUT_TRANSCRIPTION
    if model.startswith("google:"):
        # Background talk (a TV in the room) held Gemini's turn open with
        # its default detector: stricter about what STARTS a turn, quicker
        # to END one.
        settings["google_vad"] = {"start_sensitivity": "low", "end_sensitivity": "high"}
    if max_output_tokens:
        settings["max_tokens"] = max_output_tokens
    return settings


def resumed(conversation: Any, now: datetime | None = None) -> str | None:
    """What was asked when the last call dropped, if it dropped within
    ``RESUME_WINDOW`` mid-answer; else None."""
    if not conversation.messages:
        return None
    last = conversation.messages[-1]
    meta = last.metadata or {}
    if last.role != MessageRole.ASSISTANT or not meta.get("interrupted"):
        return None
    at = last.timestamp if last.timestamp.tzinfo else last.timestamp.replace(tzinfo=UTC)
    if (now or datetime.now(UTC)) - at > RESUME_WINDOW:
        return None
    return meta.get("asked") or None


async def call_instructions(agent: Any, history: str) -> str:
    """What a call tells the model: the agent's whole prompt, then the
    conversation. A realtime session sends the agent's instructions and
    never its system prompt, so the prompt is read back off the agent: the
    very prompt a typed turn sends."""
    parts = await agent.system_prompt_parts()
    prompt = "\n\n".join(part.content for part in parts)
    return f"{prompt}\n\n{history}" if history else prompt


async def realtime_for(
    ai: Any,
    *,
    conversation: Any,
    model: str,
    agent_slug: str | None,
    voice: str | None,
    instructions: str | None = None,
    max_output_tokens: int | None = None,
) -> Any:
    """The agent on ``model`` (a Pydantic AI realtime model string), built
    exactly as a turn builds it. The engine's ``instructions`` (how to talk
    on a call) lead its prompt, and ``max_output_tokens`` caps one reply."""
    from app.services.ai.domains.chat.agent_loader import resolve_agent

    config = await (resolve_agent(agent_slug) if agent_slug else resolve_agent())
    # GPT-Live takes the call manners as its own (``_model_settings``).
    if instructions and not is_gpt_live(model):
        config = replace(
            config, system_prompt=f"{instructions}\n\n{config.system_prompt}"
        )
    agent, history = await ai._prepare_agent_and_context(
        conversation, agent_config=config
    )
    return agent.realtime(
        model,
        instructions=await call_instructions(agent, history),
        model_settings=_model_settings(model, voice, max_output_tokens, instructions),
        toolsets=[CALL_TOOLS],
    )


async def drive(
    ai: Any,
    realtime: Any,
    *,
    conversation_id: str,
    model: str,
    agent_slug: str | None,
    user_id: str,
    alongside: Callable[[Any], Awaitable[None]] | None = None,
    on_event: Callable[[Any], Awaitable[None]] | None = None,
    on_saved: Callable[[float], Awaitable[None]] | None = None,
    on_drawn: Callable[[list[str]], Awaitable[None]] | None = None,
) -> None:
    """Run one call to its end: the agent's tools in a turn's context, each
    finished turn saved into the conversation, the priced usage ledgered.
    ``alongside`` runs beside the events for the length of the call (the
    audio both ways), ``on_event`` sees every event, ``on_saved`` hears of
    each saved turn with the call's cost so far, and ``on_drawn`` of the
    cards a step drew as it finishes - so a chart is up while it is being
    talked about, not once the turn is saved."""
    started = datetime.now(UTC)
    usage = None
    log = TurnLog()
    provider, _, bare = model.rpartition(":")
    # The call so far, at the last saved turn: each turn keeps its share.
    so_far = {"input_tokens": 0, "output_tokens": 0, "cost": 0.0}
    rates = await usage_recording.realtime_price(bare)

    async def keep(
        session: Any, turn: tuple[str, str, list[dict[str, Any]]], interrupted: bool
    ) -> float:
        """Save one turn with its share of the call; the call's cost so far."""
        nonlocal so_far
        now = {
            "input_tokens": session.usage.input_tokens or 0,
            "output_tokens": session.usage.output_tokens or 0,
            "cost": usage_recording.realtime_cost(rates, session.usage),
        }
        await save_turn(
            ai,
            conversation_id,
            *turn,
            model=bare,
            provider=provider or "openai",
            usage={k: now[k] - so_far[k] for k in now},
            interrupted=interrupted,
        )
        so_far = now
        return float(now["cost"])

    try:
        with (
            memory_user(
                user_id, agent_slug=agent_slug, conversation_id=conversation_id
            ),
            reading_stage(),
            card_stage() as drawn,
        ):
            log.drawn = drawn
            async with realtime.session() as session:
                beside = asyncio.create_task(alongside(session)) if alongside else None
                try:
                    async for event in session:
                        if on_event:
                            await on_event(event)
                        if log.observe(event) and (turn := log.take()):
                            log.drawn = drawn
                            cost = await keep(session, turn, interrupted=False)
                            if on_saved:
                                await on_saved(cost)
                        if log.shown and on_drawn:
                            await on_drawn(log.shown)
                finally:
                    # A dropped call still used what it used, and still
                    # said and ran what it did: the turn it cut is kept.
                    usage = session.usage
                    if cut := log.take():
                        try:
                            await keep(session, cut, interrupted=True)
                        except Exception:
                            logger.exception("Saving a cut-off turn failed")
                    if beside:
                        beside.cancel()
    except Exception:
        logger.exception("A live call ended with an error")
    finally:
        if usage is not None:
            await usage_recording.record_realtime(
                bare,
                usage,
                seconds=(datetime.now(UTC) - started).total_seconds(),
                conversation_id=conversation_id,
                rates=rates,
                user_id=user_id,
            )
