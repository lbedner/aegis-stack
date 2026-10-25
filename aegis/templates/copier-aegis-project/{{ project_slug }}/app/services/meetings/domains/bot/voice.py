"""What the bot says aloud in a call, where the stack has a voice: the
AI service's text to speech (``ai[voice]``), in the voice profile Overseer
speaks in. Without one, or when the speech cannot be made, it says nothing
aloud; what it says is in the chat either way."""

from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.discovery import optional
from app.core.log import logger
from app.services.meetings.domains.moments.detectors import SENTENCES

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
