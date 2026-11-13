"""A speech server you run (``local_server``), Kokoro-FastAPI first: the
OpenAI client at SPEECH_BASE_URL, sent only what its profile (``SERVERS``)
says it takes.

Its voices go by ids of their own (``local_server:af_heart``), since the
in-app Kokoro has the same names and a voice's id says its provider; the
server is sent the name it knows (``served_as``). Any such id is one of its
voices (``voice_of``), so a profile on one opens before the server has been
asked; a listing has those it is known to have, and the rest once it has
been asked for them (``ask_for_voices``).
"""

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
import logging
import time
from typing import Any

from app.core import speech_server
from app.core.voice_settings import setting_default

from .. import library, local
from ..models import (
    DEFAULT_TTS_MODELS,
    ModelInfo,
    ProviderInfo,
    SpeechRequest,
    SpeechResult,
    TTSProvider,
    VoiceInfo,
)
from .providers import OpenAITTSProvider

logger = logging.getLogger(__name__)

PROVIDER_ID = TTSProvider.LOCAL_SERVER.value
PREFIX = f"{PROVIDER_ID}:"
# What a server is asked with in place of a key it does not take. Never
# none: given none, the OpenAI client sends OPENAI_API_KEY to the server.
NO_KEY = "speech-server"


@dataclass(frozen=True)
class Server:
    """What one speech server takes beyond OpenAI's speech endpoint."""

    name: str
    # Sent for a whole file, past OpenAI's own fields.
    whole: Mapping[str, Any]
    # The voices it is known to have before it is asked.
    voices: tuple[str, ...]


SERVERS = {
    "kokoro_fastapi": Server(
        name=speech_server.NAME,
        whole={"stream": False},  # it streams unless told not to
        voices=local.KOKORO_VOICES,
    ),
}
# The one SPEECH_SERVER names so far, so the catalog's from the start.
SERVER = SERVERS[setting_default("SPEECH_SERVER")]

PROVIDER = ProviderInfo(
    id=PROVIDER_ID,
    # Its voices share their names with the in-app Kokoro's; this says
    # which plays them.
    name=SERVER.name,
    type="tts",
    requires_api_key=False,
    is_local=True,
    description=f"A speech server you run ({SERVER.name}), at SPEECH_BASE_URL",
)
MODELS = [
    ModelInfo(
        id=DEFAULT_TTS_MODELS[TTSProvider.LOCAL_SERVER],
        name="Kokoro",
        provider_id=PROVIDER_ID,
        description=f"Kokoro-82M on {SERVER.name}; streams as it speaks",
        supports_streaming=True,
    )
]


def served_as(voice: str) -> str:
    """A voice as its server names it: the catalog's id less its prefix."""
    return voice.removeprefix(PREFIX)


def _voice(name: str) -> VoiceInfo:
    return local.kokoro_voice(
        name, PROVIDER_ID, [m.id for m in MODELS], id=PREFIX + name
    )


def voice_of(voice_id: str) -> VoiceInfo | None:
    """The server's voice by its catalog id, listed or not; one it does not
    have is refused when it is asked to say a line."""
    return _voice(served_as(voice_id)) if voice_id.startswith(PREFIX) else None


VOICES = [_voice(name) for name in SERVER.voices]
# Those it lists past the known ones, by id, as they come in.
LISTED: dict[str, VoiceInfo] = {}


class ServerTTSProvider(OpenAITTSProvider):
    """A speech server over OpenAI's speech endpoint: the voice as it names
    it, the whole file asked for as its profile says."""

    provider_type = TTSProvider.LOCAL_SERVER

    def __init__(self, base_url: str, server: str, model: str, voice: str) -> None:
        super().__init__(api_key=NO_KEY, model=model, voice=voice, base_url=base_url)
        self.whole = SERVERS[server].whole

    def _speech_kwargs(self, request: SpeechRequest) -> dict[str, Any]:
        voice = served_as(request.voice or self.default_voice)
        return super()._speech_kwargs(request) | {"voice": voice}

    async def synthesize(self, request: SpeechRequest) -> SpeechResult:
        """The whole file, charted with how long it took (Inference > Speech)."""
        started = time.perf_counter()
        said = await super().synthesize(request)
        await speech_server.charted("file", time.perf_counter() - started)
        return said

    async def synthesize_stream(self, request: SpeechRequest) -> AsyncIterator[bytes]:
        """The stream, charted with how long its first audio took, once it
        ends: the chart's write never holds back the audio."""
        started, first = time.perf_counter(), None
        async for chunk in super().synthesize_stream(request):
            if first is None:
                first = time.perf_counter() - started
            yield chunk
        if first is not None:
            await speech_server.charted("stream", first)


async def fill(url: str) -> None:
    """Every voice the server at ``url`` lists into ``LISTED``. Where it
    cannot be read, why in the log, and it is asked again next time: it is
    often started after the app."""
    try:
        for name in await speech_server.voices(url):
            if name not in SERVER.voices:
                LISTED[PREFIX + name] = _voice(name)
    except Exception as e:  # the server's own (down, refusing) or its answer
        library.TRIED.discard(PREFIX + url)
        logger.warning(f"The speech server at {url} could not list its voices: {e!r}")


def ask_for_voices() -> None:
    """The configured server's voices asked for in the background, once per
    address (``library.load_once``); nothing where none is set."""
    from app.core.config import settings

    if url := speech_server.reach(settings):
        library.load_once(PREFIX + url, lambda: fill(url))
