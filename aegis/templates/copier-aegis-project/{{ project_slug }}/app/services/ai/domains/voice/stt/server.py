"""A hearing server you run: any OpenAI-compatible transcription server at
HEARING_BASE_URL (speaches first, ``inference[speaches]``), heard through
OpenAI's client as Kokoro-FastAPI is spoken through it (``tts/server.py``).
Its models are what the server holds, by the names it gives them, listed
once it has been asked (``ask_for_models``); the call setup's Hears lists
them while it answers."""

from __future__ import annotations

import logging
import time

from app.core import hearing_server, series, speech_server

from .. import library
from ..models import (
    DEFAULT_STT_MODELS,
    AudioInput,
    ModelInfo,
    ProviderInfo,
    STTProvider,
    TranscriptionResult,
    server_url,
)
from .providers import OpenAIWhisperProvider

logger = logging.getLogger(__name__)

PROVIDER_ID = STTProvider.HEARING_SERVER.value

PROVIDER = ProviderInfo(
    id=PROVIDER_ID,
    name="Hearing server",
    type="stt",
    requires_api_key=False,
    is_local=True,
    description="A transcription server you run (speaches), at HEARING_BASE_URL",
)
MODELS = [
    ModelInfo(
        id=DEFAULT_STT_MODELS[STTProvider.HEARING_SERVER],
        name="Parakeet TDT 0.6B v3 (speaches)",
        provider_id=PROVIDER_ID,
        description="NVIDIA Parakeet on your hearing server; 25 languages",
        supports_streaming=False,
    )
]
# Those it holds past the known one, by id, as they come in.
LISTED: dict[str, ModelInfo] = {}


class ServerSTTProvider(OpenAIWhisperProvider):
    """A hearing server over OpenAI's transcription endpoint."""

    provider_type = STTProvider.HEARING_SERVER

    def __init__(self, base_url: str, model: str) -> None:
        super().__init__(api_key=speech_server.NO_KEY, model=model, base_url=base_url)

    async def transcribe(self, audio: AudioInput) -> TranscriptionResult:
        """What was said, charted with how long it took (its Inference page)."""
        started = time.perf_counter()
        heard = await super().transcribe(audio)
        await series.record({hearing_server.LATENCY: time.perf_counter() - started})
        return heard


async def fill(url: str) -> None:
    """Every hearing model the server at ``url`` holds into ``LISTED``. Where
    it cannot be read, why in the log, and it is asked again next time: it
    is often started after the app."""
    reading = await hearing_server.read(url)
    if not reading.available:
        library.TRIED.discard(PROVIDER_ID + url)
        logger.warning(
            f"The hearing server at {url} could not list its models: {reading.error}"
        )
        return
    known = {m.id for m in MODELS}
    for model in reading.models:
        if model not in known:
            LISTED[model] = ModelInfo(
                id=model,
                name=model,
                provider_id=PROVIDER_ID,
                description="On your hearing server",
                supports_streaming=False,
            )


def ask_for_models() -> None:
    """The configured server's models asked for in the background, once per
    address (``library.load_once``); nothing where none is set."""
    from app.core.config import settings

    if url := server_url(PROVIDER_ID, settings):
        library.load_once(PROVIDER_ID + url, lambda: fill(url))
