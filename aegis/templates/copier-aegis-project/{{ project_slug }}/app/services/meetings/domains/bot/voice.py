"""What the bot says aloud in a call, where the stack has a voice: the
AI service's text to speech (``ai[voice]``), in the voice profile Overseer
speaks in. Without one, or when the speech cannot be made, it says nothing
aloud; what it says is in the chat either way."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.discovery import optional
from app.core.log import logger
from app.services.meetings.domains.actions.live import LIVE
from app.services.meetings.domains.actions.registry import ANSWERS, SURFACE
from app.services.meetings.domains.moments.detectors import SENTENCES
from app.services.meetings.domains.moments.service import answerer

TTS = "app.services.ai.domains.voice.tts"
AI = "app.services.ai.service"


async def voice_of(session: AsyncSession) -> Any | None:
    """The settings the bot speaks with: the stack's, in its active voice
    profile where it keeps them (with a database); None with no voice to
    speak in."""
    if optional(TTS) is None:
        return None
    profiles = getattr(optional(AI), "profiles", None)
    return (
        settings
        if profiles is None
        else await profiles.active_settings(session, settings)
    )


async def spoken(text: str, voice: Any | None) -> bytes | None:
    """``text`` as speech (TTS's audio) in ``voice`` (``voice_of``); None
    with no voice to say it."""
    if voice is None:
        return None
    ai = optional(AI)
    try:
        result = await ai.TTSService(voice).synthesize(ai.SpeechRequest(text=text))
    except Exception:
        logger.exception("The bot's speech could not be made; it writes only")
        return None
    return result.audio


def sentences(text: str) -> list[str]:
    """``text`` as it is said aloud, a sentence at a time: written for a
    chat, its markdown is made plain first (the AI service's
    ``to_spoken``), lists and all, where the stack has it."""
    plain = getattr(optional(AI), "to_spoken", lambda said: said)(text)
    return SENTENCES.split(plain.strip())


async def live_engine_of(session: AsyncSession, voice: Any | None) -> Any | None:
    """The live engine her answers in a call are made on: her voice
    profile's (``voice``, from ``voice_of``: the bot runs in a worker, whose
    settings are the .env's), where she is the one answering (``answerer``)
    and the stack has one enabled; else None."""
    engines = getattr(optional(AI), "live_engines", None)
    if voice is None or engines is None or answerer() != ANSWERS:
        return None
    return await engines.resolve(session, voice.VOICE_LIVE_ENGINE)


@asynccontextmanager
async def live(
    call: Any, voice: Any | None, engine: Any | None, owner_user_id: int | None
) -> AsyncGenerator[Any | None]:
    """Her live voice in this call (the AI service's ``live_voice``, on
    ``engine``: ``live_engine_of``), bound to ``LIVE`` for its length: a
    question put to her is answered aloud as she makes the answer, streamed
    into the call (``call.stream``). None without a voice, a live engine,
    or a call that comes up."""
    ai = optional(AI)
    if voice is None or engine is None or getattr(ai, "live_voice", None) is None:
        yield None
        return
    async with ai.live_voice(
        ai.AIService(settings),
        engine=engine,
        play=call.stream,
        surface=SURFACE,
        user_id="default" if owner_user_id is None else str(owner_user_id),
        voice=getattr(voice, "TTS_VOICE", None),
        on_end=call.hush,  # however the call ends, the mic it held closes
    ) as spoken:
        token = LIVE.set(spoken)
        try:
            yield spoken
        finally:
            LIVE.reset(token)
            await call.hush()
