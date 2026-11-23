"""A live call: one path for every engine.

The realtime model IS the brain: the voice agent's prompt, tools and code
mode, built exactly as a turn builds it. The app's server holds the
provider session (the key never leaves it) and the page carries the audio
over the app's own WebSocket (``routes/partials/chat_live.py``). ``drive``
runs the agent's tools in a turn's context, saves each finished turn into
the conversation (what was heard, what was said, the steps - so the thread
shows it like a typed turn), and bills the call's ledger row as it runs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from pydantic_ai.messages import ModelMessage, RealtimeSessionErrorEvent
from pydantic_ai.toolsets import FunctionToolset
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.services.ai.domains.chat.cards import card_stage
from app.services.ai.domains.chat.chat_kit import ChatMessage, to_model_history
from app.services.ai.domains.chat.chat_kit.models import ChatRole
from app.services.ai.domains.chat.readings import reading_stage
from app.services.ai.domains.chat.user_memory import memory_user
from app.services.ai.domains.spend import calls
from app.services.ai.domains.voice import live_engines
from app.services.ai.domains.voice.call_turns import (
    END_CALL as END_CALL,  # what the call path reads it as
)
from app.services.ai.domains.voice.call_turns import TurnLog, end_call, save_turn
from app.services.ai.domains.voice.cascade import connection as cascade
from app.services.ai.domains.voice.live_engines import call_voice, is_gpt_live
from app.services.ai.domains.voice.spoken import pronunciation_instructions
from app.services.ai.models import AIProvider, MessageRole

# What OpenAI transcribes the caller's side with: a saved turn needs both
# sides, and only OpenAI's realtime models need asking.
INPUT_TRANSCRIPTION = "gpt-4o-mini-transcribe"
# How fast OpenAI's realtime models will speak (``openai_output_speed``).
OPENAI_SPEEDS = (0.25, 1.5)
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


def _elapsed(started: datetime) -> float:
    """A call's length so far, in seconds: what a model priced by time bills."""
    return (datetime.now(UTC) - started).total_seconds()


# A call ends on the agent's tool (``call_turns.end_call``), not on a
# phrase the page listens for: a model can drop a phrase. The page hangs up
# when it sees the call.
CALL_TOOLS = FunctionToolset([end_call])


def _model_settings(
    model: str,
    voice: Any,
    max_output_tokens: int | None,
    instructions: str | None = None,
) -> dict[str, Any]:
    """The session's settings for its provider. Each speaks the voice's
    own for its vendor (``voice``: settings sounding as the active voice),
    else its own; OpenAI's realtime models at the voice's speed. OpenAI
    transcribes the caller only when asked, Gemini by default."""
    settings: dict[str, Any] = {}
    speaks = call_voice(model, voice.TTS_VOICES)
    if model.startswith("openai:"):
        if speaks:
            settings["openai_voice"] = speaks
        if is_gpt_live(model):
            # GPT-Live's voice takes the call manners, when to hand off and
            # the running summary (``realtime_for``); its thread rides as past
            # turns, the agent's prompt is the backend's. It transcribes
            # itself.
            if instructions:
                settings["openai_live_instructions"] = instructions
            return settings
        settings["input_transcription_model"] = INPUT_TRANSCRIPTION
        low, high = OPENAI_SPEEDS
        settings["openai_output_speed"] = min(max(voice.TTS_SPEED, low), high)
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
    return _and_history("\n\n".join(part.content for part in parts), history)


def _and_history(text: str, history: str) -> str:
    """``text``, then the conversation so far, when there is one."""
    return f"{text}\n\n{history}" if history else text


# What GPT-Live takes as past turns: OpenAI refuses a seed
# (``session.input``) of more than 128 items or 8,192 tokens, measured
# 2026-11-22; tokens at 3 characters, which errs short.
LIVE_SEED_ITEMS = 128
LIVE_SEED_CHARS = 8_192 * 3


def _seed_size(conversation: Any) -> int:
    """How many of the thread's latest turns GPT-Live is seeded with."""
    from app.services.ai.service.prompt import replayed, steps_ahead

    room, size = LIVE_SEED_CHARS, 0
    for message in reversed(replayed(conversation.messages)[-LIVE_SEED_ITEMS:]):
        room -= len(steps_ahead(message)) + len(message.content)
        if room < 0:
            break
        size += 1
    return size


def _seeded(setup: Any, size: int) -> list[ModelMessage]:
    """The thread's latest ``size`` turns, as far back as her prompt's
    window reaches (``setup.history_start``), as the turns they were: a
    reply with what its turn did. GPT-Live's voice hears them, and its
    backend reads them (15,650 tokens seeded, 1,733 not, 2026-11-22)."""
    from app.services.ai.service.prompt import replayed, steps_ahead

    turns = replayed(setup.conversation.messages)
    tail = turns[max(setup.history_start, len(turns) - size) :]
    return to_model_history(
        [
            ChatMessage(
                role=cast(ChatRole, m.role.value), content=steps_ahead(m) + m.content
            )
            for m in tail
        ]
    )


async def realtime_for(
    ai: Any,
    *,
    conversation: Any,
    model: str,
    agent_slug: str | None,
    voice: Any,
    user_id: str,
    owner_user_id: int | None = None,
    subject: str | None = None,
    admin: bool | None = None,
    instructions: str | None = None,
    max_output_tokens: int | None = None,
    hang_up: bool = True,
) -> tuple[Any, str]:
    """The agent on ``model`` (a Pydantic AI realtime model string), built
    for the caller (``user_id``, ``owner_user_id``, ``admin``) about the
    call's ``subject`` by the function a typed turn builds her with
    (``_build_turn``), and the slug of the agent she is (``held_agent``:
    ``agent_slug``, else the one the conversation is held with), for
    ``drive`` to bind. The engine's ``instructions`` (how
    to talk on a call) lead its prompt, and ``max_output_tokens`` caps one
    reply. Without ``hang_up`` she has no ``end_call``: a call that answers
    one question after another ends when its caller ends it. The voice's
    delivery (``voice``: settings sounding as the active voice) and the
    pronunciation list ride with the call manners, which reach whichever
    model speaks on each engine; a chain's own speech takes the delivery
    itself."""
    from app.services.ai.service.chat import held_agent

    hands_off = live_engines.LIVE_HANDS_OFF if is_gpt_live(model) else None
    style = None if cascade.serves(model) else voice.TTS_INSTRUCTIONS
    manners = (instructions, style, pronunciation_instructions(), hands_off)
    instructions = "\n\n".join(filter(None, manners))
    # A call answers as its agent without taking the thread: typed turns
    # after it would answer as the voice model.
    config = await held_agent(conversation, agent_slug, hand_over=False)
    slug = config.slug
    # GPT-Live's voice takes the call manners as its own (``_model_settings``).
    if not is_gpt_live(model):
        config = config.led_by(instructions)
    seeded = _seed_size(conversation) if is_gpt_live(model) else 0
    setup = await ai._build_turn(
        conversation,
        config,
        user_id=user_id,
        subject=subject,
        owner_user_id=owner_user_id,
        admin=admin,
        seeded=seeded,
    )
    agent, history = setup.agent, setup.conversation_context
    past = None
    if is_gpt_live(model):
        # Its voice hears the thread as every other engine does: told only
        # the manners, it made answers up (2026-11-16). The summary rides in
        # its instructions; the latest turns as past turns (``_seeded``).
        past = _seeded(setup, seeded)
        instructions = _and_history(instructions, setup.history_summary)
    realtime = agent.realtime(
        await cascade.for_call(ai, model, user_id=user_id)
        if cascade.serves(model)
        else model,
        instructions=await call_instructions(agent, history),
        model_settings=_model_settings(model, voice, max_output_tokens, instructions),
        toolsets=[CALL_TOOLS] if hang_up else [],
        # GPT-Live's voice: its thread as past turns (``_seeded``). Every
        # other engine reads it in its prompt.
        message_history=past,
    )
    return realtime, slug


async def open_call(
    ai: Any,
    engine: Any,
    *,
    user_id: str,
    surface: str,
    agent_slug: str | None,
    voice: Any,
    conversation: Any = None,
    owner_user_id: int | None = None,
    subject: str | None = None,
    admin: bool | None = None,
    hang_up: bool = True,
    instructions: str | None = None,
) -> tuple[Any, Any, str]:
    """A live call on ``engine`` (``live_engines``): the conversation it
    saves into (``conversation``, else a new one of ``surface``'s for
    ``user_id`` about ``subject``), her, built for it on the engine's
    model with its call manners (``realtime_for``), or the caller's
    (``instructions``: a call with others in it, such as a meeting), in
    ``voice`` (settings sounding as the active voice), and the agent she
    is, for ``drive``."""
    model = live_engines.realtime_model(engine)
    if conversation is None:
        conversation = await ai.conversation_manager.create_conversation(
            provider=AIProvider(engine.llm.served_by.slug),
            model=model,
            user_id=user_id,
            surface=surface,
            subject=subject,
        )
    realtime, slug = await realtime_for(
        ai,
        conversation=conversation,
        model=model,
        agent_slug=agent_slug,
        voice=voice,
        user_id=user_id,
        owner_user_id=owner_user_id,
        subject=subject,
        admin=admin,
        instructions=engine.instructions if instructions is None else instructions,
        max_output_tokens=engine.max_output_tokens,
        hang_up=hang_up,
    )
    return conversation, realtime, slug


async def drive(
    ai: Any,
    realtime: Any,
    *,
    ledger: AsyncSession,
    conversation_id: str,
    model: str,
    agent_slug: str | None,
    user_id: str,
    owner_user_id: int | None = None,
    subject: str | None = None,
    admin: bool | None = None,
    alongside: Callable[[Any], Awaitable[None]] | None = None,
    on_event: Callable[[Any], Awaitable[None]] | None = None,
    on_saved: Callable[[float], Awaitable[None]] | None = None,
    on_drawn: Callable[[list[str]], Awaitable[None]] | None = None,
    on_turn: Callable[[tuple[str, str, list[dict[str, Any]]]], Awaitable[None]]
    | None = None,
) -> CallEnd:
    """Run one call to its end, and say who ended it (``CallEnd``): the
    agent's tools in a turn's context, each finished turn saved into the
    conversation, the call's ledger row billed as each is (``call_cost``).
    ``alongside`` runs beside the events for the length of the call (the
    audio both ways), ``on_event`` sees every event, ``on_saved`` hears of
    each saved turn with the call's own cost so far, and ``on_drawn`` of the
    cards a step drew as it finishes - so a chart is up while it is being
    talked about, not once the turn is saved. ``on_turn`` has each finished
    turn (what was heard, what was said, its steps) before it is saved.
    The call's row is written on ``ledger``, each write committed."""
    started = datetime.now(UTC)
    usage = None
    ended: CallEnd = "provider"
    log = TurnLog()
    provider, bare = live_engines.split_model(model)
    # The call so far, at the last saved turn: each turn keeps its share.
    so_far = {"input_tokens": 0, "output_tokens": 0, "cost": 0.0}
    rates = await calls.realtime_price(bare)
    # The rates of the model it hands its work to, read once it has; only
    # a model priced by time hands its work elsewhere (GPT-Live).
    delegated: calls.llm_queries.Rates | None = None
    looked = not calls.per_second(rates)

    async def handed_to(session: Any) -> None:
        nonlocal delegated, looked
        if not looked and (name := calls.delegated_to(session)):
            looked = True
            delegated = await calls.realtime_price(name)

    # The call's ledger row, written beside the audio rather than ahead of
    # it; each bill waits for it (``row``).
    opening: asyncio.Task[int | None] | None = None

    async def row() -> int | None:
        """The call's ledger row once written; None when it was not."""
        return await opening if opening is not None else None

    async def keep(
        session: Any, turn: tuple[str, str, list[dict[str, Any]]], interrupted: bool
    ) -> float:
        """Save one turn with its share of the call, billing the call's row;
        the call's cost so far."""
        nonlocal so_far
        await handed_to(session)
        now = {
            "input_tokens": session.usage.input_tokens or 0,
            "output_tokens": session.usage.output_tokens or 0,
            "cost": await calls.bill_realtime(
                ledger,
                await row(),
                session.usage,
                seconds=_elapsed(started),
                rates=rates,
                delegated=delegated,
            ),
        }
        shares: dict[str, Any] = {k: now[k] - so_far[k] for k in now}
        if log.first_word_ms is not None:
            shares["first_word_ms"] = log.first_word_ms
            log.first_word_ms = None
        await save_turn(
            ai,
            conversation_id,
            *turn,
            model=bare,
            provider=provider or "openai",
            usage=shares,
            interrupted=interrupted,
        )
        so_far = now
        return float(now["cost"])

    try:
        with (
            memory_user(
                user_id,
                owner_user_id=owner_user_id,
                agent_slug=agent_slug,
                conversation_id=conversation_id,
                subject=subject,
                admin=admin,
            ),
            reading_stage(),
            card_stage() as drawn,
        ):
            log.drawn = drawn
            async with realtime.session() as session:
                opening = asyncio.create_task(
                    calls.open_realtime(
                        ledger, bare, conversation_id=conversation_id, user_id=user_id
                    )
                )
                # A turn the call hands off (a picture looked at) names
                # this row, so the call's thinking is read from its turns.
                handing = calls.handing_off.set(opening)
                beside = asyncio.create_task(alongside(session)) if alongside else None
                try:
                    async for event in session:
                        if on_event:
                            await on_event(event)
                        if isinstance(event, RealtimeSessionErrorEvent):
                            # Work the session lost (GPT-Live's backend
                            # failing or stopping short): the call carries
                            # on, but it went quiet with no word of why
                            # (2026-11-22).
                            logger.warning(
                                "A live call lost work",
                                error=event.message,
                                code=event.code,
                                model=model,
                            )
                        if log.observe(event) and (turn := log.take()):
                            if on_turn:
                                await on_turn(turn)
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
                    await handed_to(session)
                    if cut := log.take():
                        try:
                            await keep(session, cut, interrupted=True)
                        except Exception:
                            logger.exception("Saving a cut-off turn failed")
                    if beside:
                        beside.cancel()
                    calls.handing_off.reset(handing)
    except Exception:
        ended = "error"
        logger.exception("A live call ended with an error")
    finally:
        seconds = _elapsed(started)
        if usage is not None:
            await calls.bill_realtime(
                ledger,
                await row(),
                usage,
                seconds=seconds,
                rates=rates,
                delegated=delegated,
                success=ended != "error",
            )
        logger.info(
            "Live call ended",
            ended_by=ended,
            seconds=round(seconds, 1),
            model=model,
            conversation_id=conversation_id,
        )
    return ended
