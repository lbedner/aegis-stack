"""Kokoro speaking in the app's own process (``kokoro-onnx``): no server
and no key. Its two model files (about 120MB) are fetched from the
kokoro-onnx release on first use and kept in the cache."""

import asyncio
import logging
from pathlib import Path
from typing import Any

from .. import local
from ..models import (
    DEFAULT_TTS_VOICES,
    TTS_FORMATS,
    SpeechRequest,
    SpeechResult,
    TTSProvider,
)
from . import length, realtime
from .providers import BaseTTSProvider

logger = logging.getLogger(__name__)

RELEASE = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
)
FILES = ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin")
CACHE = Path.home() / ".cache" / "kokoro-onnx"
# Kokoro's language for the accent a voice's first letter names (``local``).
LANGUAGES = {"a": "en-us", "b": "en-gb"}


@local.loaded_once
def model() -> Any:
    """The one Kokoro this process speaks with."""
    from kokoro_onnx import Kokoro

    return Kokoro(*(str(local.fetched(f"{RELEASE}/{name}", CACHE)) for name in FILES))


class KokoroProvider(BaseTTSProvider):
    """Kokoro-82M in-process, at Kokoro's 24kHz (the Realtime API's rate,
    so ``realtime.wav`` wraps it). No delivery instructions; a speed."""

    provider_type = TTSProvider.KOKORO

    def __init__(self, voice: str = DEFAULT_TTS_VOICES[TTSProvider.KOKORO]) -> None:
        self.default_voice = voice

    def _said(self, request: SpeechRequest) -> bytes:
        voice = request.voice or self.default_voice
        samples, _ = model().create(
            request.text,
            voice=voice,
            speed=request.speed or 1.0,
            lang=LANGUAGES.get(voice[0], LANGUAGES["a"]),
        )
        return realtime.wav(realtime.pcm16(samples))

    async def synthesize(self, request: SpeechRequest) -> SpeechResult:
        try:
            audio = await asyncio.to_thread(self._said, request)
        except Exception as e:
            logger.error(f"Kokoro synthesis failed: {e}")
            raise RuntimeError(f"Speech synthesis failed: {e}") from e
        return SpeechResult(
            audio=audio,
            format=TTS_FORMATS[self.provider_type],
            duration_seconds=length.wav_seconds(audio),
            provider=self.provider_type,
        )
