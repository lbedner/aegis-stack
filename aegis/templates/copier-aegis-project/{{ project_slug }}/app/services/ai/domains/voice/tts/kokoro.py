"""Kokoro speaking in the app's own process (``kokoro-onnx``): no server
and no key. Its two model files (about 120MB) are fetched from the
kokoro-onnx release on first use and kept in the cache."""

import asyncio
import logging
import os
from pathlib import Path
import tempfile
from typing import Any

import httpx

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


def fetched(name: str) -> Path:
    """A model file in the cache, downloaded into it first when absent
    (whole into a file of its own, then moved, so a cut-off download, or
    another process fetching it too, never leaves half a file)."""
    path = CACHE / name
    if path.exists():
        return path
    CACHE.mkdir(parents=True, exist_ok=True)
    fd, partial = tempfile.mkstemp(dir=CACHE, suffix=".partial")
    logger.info(f"Fetching Kokoro's {name} into {CACHE}")
    try:
        with (
            os.fdopen(fd, "wb") as out,
            httpx.stream(
                "GET", f"{RELEASE}/{name}", follow_redirects=True, timeout=60
            ) as response,
        ):
            response.raise_for_status()
            for chunk in response.iter_bytes(1 << 20):
                out.write(chunk)
        os.replace(partial, path)
    except BaseException:
        Path(partial).unlink(missing_ok=True)
        raise
    return path


@local.loaded_once
def model() -> Any:
    """The one Kokoro this process speaks with."""
    from kokoro_onnx import Kokoro

    return Kokoro(*(str(fetched(name)) for name in FILES))


def pcm16(samples: Any) -> bytes:
    """Kokoro's float samples (a numpy array) as 16-bit PCM."""
    return (samples.clip(-1, 1) * 32767).astype("<i2").tobytes()


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
        return realtime.wav(pcm16(samples))

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
