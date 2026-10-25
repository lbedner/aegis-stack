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
from typing import Any, Literal

from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartEndEvent,
    RealtimeTurnCompleteEvent,
    SpeechPart,
)
from pydantic_ai.toolsets import FunctionToolset

from app.core.log import logger
from app.services.ai.domains.chat.cards import attach_cards, card_stage
from app.services.ai.domains.chat.readings import reading_stage
from app.services.ai.domains.chat.user_memory import memory_user
from app.services.ai.domains.spend import recording as usage_recording
from app.services.ai.domains.voice.catalog import GEMINI_PREBUILT, get_voice
from app.services.ai.domains.voice.live_engines import is_gpt_live
from app.services.ai.domains.voice.models import TTSProvider
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
# Who ended a call: the person (the page hung up), the provider (it closed
# the session, the page still on), or an error.
CallEnd = Literal["page", "provider", "error"]
# How long a call whose events stopped waits for the page to have hung up
# before it reads as the provider's end.
HANG_UP_GRACE = 0.5


def end_call() -> str:
    """End the call. Use it once they have said they are done - a goodbye,
    "that's all", thanks with nothing more to ask - right after your short
    goodbye, and say nothing after it. Never on a turn with no words of
    theirs in it (a noise, a breath, your own voice heard back): that is
    not a goodbye, so carry on or ask what they meant."""
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
        # The cards the call's steps draw (its card stage), moved onto the
        # step that drew them; the call's, not a turn's.
        self.drawn: list[dict[str, Any]] = []
        # The cards the last event's step drew, for the page at once.
        self.shown: list[str] = []

    def _reset(self) -> None:
        self.heard: list[str] = []
        self.said: list[str] = []
        self.trace: list[dict[str, Any]] = []

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
            finished = record_tool_result(self.trace, event)
            self.shown = [marker["id"] for marker in self.drawn]
            attach_cards(finished, self.drawn)
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


def call_voice(model: str, voice: str | None) -> str | None:
    """The voice a call on ``model`` speaks: the profile's ``voice`` where
    the engine's provider has it (one voice for the agent's calls and
    spoken lines), else OpenAI's recommended one, else (Gemini) its own,
    None."""
    spoken = get_voice(voice) if voice else None
    by = spoken.provider_id if spoken else None
    if model.startswith("openai:"):
        return voice if by == TTSProvider.OPENAI else OPENAI_VOICE
    # Gemini Live speaks its 30 prebuilt voices, not its library's others.
    prebuilt = by == TTSProvider.GEMINI and voice in GEMINI_PREBUILT
    return voice if model.startswith("google:") and prebuilt else None


def _model_settings(
    model: str,
    voice: str | None,
    max_output_tokens: int | None,
    instructions: str | None = None,
) -> dict[str, Any]:
    """The session's settings for its provider. Each speaks the profile's
    voice where it has it (one voice for the agent's calls and spoken
    lines), else its own; OpenAI transcribes the caller only when asked,
    Gemini by default."""
    settings: dict[str, Any] = {}
    speaks = call_voice(model, voice)
    if model.startswith("openai:"):
        settings["openai_voice"] = speaks
        if is_gpt_live(model):
            # GPT-Live takes the call manners as its own instructions; the
            # agent's prompt is the backend's. It has no token limit and
            # transcribes itself.
            if instructions:
                settings["openai_live_instructions"] = instructions
            return settings
        settings["input_transcription_model"] = INPUT_TRANSCRIPTION
        # Sounds took its turn: a laptop's keys and room set off the default
        # detector, so it answered noise with "what's next?" and cut in on a
        # pause mid-thought. Noise filtered for a laptop mic, and a turn
        # that ends when the thought does.
        settings["openai_input_noise_reduction"] = "far_field"
        settings["openai_turn_detection"] = {"type": "semantic_vad", "eagerness": "low"}
    if model.startswith("google:"):
        if speaks:
            settings["google_voice"] = speaks
        # Background talk (a TV in the room) held Gemini's turn open with
        # its default detector: stricter about what STARTS a turn, quicker
        # to END one - but not on a breath mid-thought (Google's advice
        # against cutting in is 500-800ms of silence). Gemini has no noise
        # filter to set; the strict start is its defence against noise.
        settings["google_vad"] = {
            "start_sensitivity": "low",
            "end_sensitivity": "high",
            "silence_duration_ms": 800,
        }
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
    user_id: str,
    admin: bool | None = None,
    instructions: str | None = None,
    max_output_tokens: int | None = None,
) -> Any:
    """The agent on ``model`` (a Pydantic AI realtime model string), built
    for the caller (``user_id``, ``admin``) by the function a typed turn
    builds her with (``_build_turn``). The engine's ``instructions`` (how
    to talk on a call) lead its prompt, and ``max_output_tokens`` caps one
    reply."""
    from app.services.ai.domains.chat.agent_loader import resolve_agent

    config = await (resolve_agent(agent_slug) if agent_slug else resolve_agent())
    # GPT-Live takes the call manners as its own (``_model_settings``).
    if instructions and not is_gpt_live(model):
        config = replace(
            config, system_prompt=f"{instructions}\n\n{config.system_prompt}"
        )
    setup = await ai._build_turn(conversation, config, user_id=user_id, admin=admin)
    agent, history = setup.agent, setup.conversation_context
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
    admin: bool | None = None,
    alongside: Callable[[Any], Awaitable[None]] | None = None,
    on_event: Callable[[Any], Awaitable[None]] | None = None,
    on_saved: Callable[[float], Awaitable[None]] | None = None,
    on_drawn: Callable[[list[str]], Awaitable[None]] | None = None,
) -> CallEnd:
    """Run one call to its end, and say who ended it (``CallEnd``): the
    agent's tools in a turn's context, each finished turn saved into the
    conversation, the priced usage ledgered.
    ``alongside`` runs beside the events for the length of the call (the
    audio both ways), ``on_event`` sees every event, ``on_saved`` hears of
    each saved turn with the call's cost so far, and ``on_drawn`` of the
    cards a step drew as it finishes - so a chart is up while it is being
    talked about, not once the turn is saved."""
    started = datetime.now(UTC)
    usage = None
    ended: CallEnd = "provider"
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
                user_id,
                agent_slug=agent_slug,
                conversation_id=conversation_id,
                admin=admin,
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
                            cost = await keep(session, turn, interrupted=False)
                            if on_saved:
                                await on_saved(cost)
                        if log.shown and on_drawn:
                            await on_drawn(log.shown)
                    if beside is not None:
                        done, _ = await asyncio.wait({beside}, timeout=HANG_UP_GRACE)
                        if done:
                            ended = "page"
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
        ended = "error"
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
        logger.info(
            "Live call ended",
            ended_by=ended,
            seconds=round((datetime.now(UTC) - started).total_seconds(), 1),
            model=model,
            conversation_id=conversation_id,
        )
    return ended
