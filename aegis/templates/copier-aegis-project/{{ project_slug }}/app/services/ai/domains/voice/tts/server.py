"""A speech server you run (``local_server``), Kokoro-FastAPI first: the
OpenAI client at SPEECH_BASE_URL, sent only what its profile (``SERVERS``)
says it takes.

Its voices go by ids of their own (``local_server:af_heart``), since a
voice's id says its provider; the
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

from .. import library
from ..models import (
    DEFAULT_TTS_MODELS,
    ModelInfo,
    ProviderInfo,
    SpeechRequest,
    SpeechResult,
    TTSProvider,
    VoiceInfo,
    server_url,
)
from .providers import OpenAITTSProvider

logger = logging.getLogger(__name__)

PROVIDER_ID = TTSProvider.LOCAL_SERVER.value
PREFIX = f"{PROVIDER_ID}:"


# Kokoro v1.0's English voices, as Kokoro-FastAPI ships them. The
# prefix is the language or accent and the gender (``speech_server.traits``);
# Kokoro names no tone. Each is named by its id: half share a name with an
# OpenAI or Gemini voice (af_alloy, af_kore), and a second "Alloy" would read
# as the same one.
KOKORO_VOICES = tuple(
    (
        "af_heart af_alloy af_aoede af_bella af_jessica af_kore af_nicole af_nova "
        "af_river af_sarah af_sky am_adam am_echo am_eric am_fenrir am_liam "
        "am_michael am_onyx am_puck am_santa bf_alice bf_emma bf_isabella bf_lily "
        "bm_daniel bm_fable bm_george bm_lewis"
    ).split()
)


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
        voices=KOKORO_VOICES,
    ),
}
# The one SPEECH_SERVER names so far, so the catalog's from the start.
SERVER = SERVERS[setting_default("SPEECH_SERVER")]

PROVIDER = ProviderInfo(
    id=PROVIDER_ID,
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
    """One of its voices as the catalog lists it, its accent and gender read
    off its name (``bf_``: British, female); a name past that (a mix the
    server saved) is listed as it is."""
    accent, gender = speech_server.traits(name) or (None, None)
    return VoiceInfo(
        id=PREFIX + name,
        name=name,
        provider_id=PROVIDER_ID,
        model_ids=[m.id for m in MODELS],
        description=f"Kokoro, {accent} {gender}" if accent else "Kokoro",
        gender=gender,
        accent=accent,
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
        super().__init__(
            api_key=speech_server.NO_KEY, model=model, voice=voice, base_url=base_url
        )
        self.whole = SERVERS[server].whole

    def _speech_kwargs(self, request: SpeechRequest) -> dict[str, Any]:
        voice = served_as(request.voice or self.default_voice)
        return super()._speech_kwargs(request) | {"voice": voice}

    async def synthesize(self, request: SpeechRequest) -> SpeechResult:
        """The whole file, charted with how long it took (its Inference page)."""
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

    if url := server_url(TTSProvider.LOCAL_SERVER, settings):
        library.load_once(PREFIX + url, lambda: fill(url))
