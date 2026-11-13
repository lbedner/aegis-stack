"""A speech server you run (``tts/server.py``), Kokoro-FastAPI first: the
OpenAI client at SPEECH_BASE_URL, asked only what the server takes. The
server is a stub; the real client's requests are answered in the test."""

import asyncio
from collections.abc import Callable
import json
from typing import Any

import httpx
import pytest

from app.core import speech_server
from app.core.config import Settings, settings
from app.services.ai.domains.voice import (
    get_tts_voices,
    get_voice,
    library,
    speaking_model,
)
from app.services.ai.domains.voice.models import (
    AudioFormat,
    SpeechRequest,
    TTSProvider,
)
from app.services.ai.domains.voice.tts import (
    TTSConfig,
    get_tts_provider,
    realtime,
    server,
)
from tests._fake_dns import answering

URL = "http://localhost:8880/v1"


def test_the_provider_is_named_for_the_server_it_talks_to() -> None:
    assert server.PROVIDER.name == speech_server.NAME


def _stub(answer: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


def _served(monkeypatch: pytest.MonkeyPatch, asked: list[httpx.Request]) -> None:
    """Every request the OpenAI client makes answered with a second of WAV,
    and kept in ``asked``."""
    import openai

    real = openai.AsyncOpenAI

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        # As Kokoro-FastAPI sends it, whole or not: its header's sizes are
        # the placeholder a stream's carries (0xFFFFFFFF).
        wav = realtime.wav(b"\0\0" * 24_000)
        unsized = wav[:4] + b"\xff" * 4 + wav[8:40] + b"\xff" * 4 + wav[44:]
        return httpx.Response(200, content=unsized)

    monkeypatch.setattr(
        openai, "AsyncOpenAI", lambda **kw: real(http_client=_stub(answer), **kw)
    )


async def test_a_line_is_said_as_a_wav_in_the_servers_own_voice_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
    asked: list[httpx.Request] = []
    _served(monkeypatch, asked)
    said = get_tts_provider(TTSProvider.LOCAL_SERVER, server_url=URL)

    result = await said.synthesize(
        SpeechRequest(
            text="Hello", voice="local_server:bm_george", instructions="Whisper"
        )
    )

    [request] = asked
    assert str(request.url) == f"{URL}/audio/speech"
    assert json.loads(request.content) == {
        "model": "kokoro",
        "input": "Hello",
        "voice": "bm_george",
        "response_format": "wav",
        "stream": False,
    }
    # The client's own key, never the OpenAI one from the environment.
    assert "sk-real" not in request.headers["authorization"]
    assert (result.format, result.duration_seconds, result.provider) == (
        AudioFormat.WAV,
        1.0,
        TTSProvider.LOCAL_SERVER,
    )


async def test_each_call_is_charted_for_the_speech_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """How long a whole file took, and a stream until its first audio
    (Overseer > Inference > Speech)."""
    charted: list[str] = []

    async def chart(kind: str, seconds: float) -> None:
        charted.append(kind)

    monkeypatch.setattr(speech_server, "charted", chart)
    _served(monkeypatch, [])
    said = get_tts_provider(TTSProvider.LOCAL_SERVER, server_url=URL)
    request = SpeechRequest(text="Hello", voice="local_server:bm_george")

    await said.synthesize(request)
    streamed = [chunk async for chunk in said.synthesize_stream(request)]

    assert len(streamed) > 1
    assert charted == ["file", "stream"]


def test_a_shell_on_the_host_reaches_a_server_named_for_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Settings, "is_docker", property(lambda self: False))
    named = settings.model_copy(
        update={
            "TTS_PROVIDER": TTSProvider.LOCAL_SERVER.value,
            "SPEECH_BASE_URL": "http://host.docker.internal:8880/v1",
        }
    )

    config = TTSConfig.from_settings(named)

    assert config.server_url == URL
    assert (config.get_model(), config.get_voice()) == (
        "kokoro",
        "local_server:af_heart",
    )


async def test_the_server_is_refused_until_its_address_is_set() -> None:
    unset = TTSConfig(provider=TTSProvider.LOCAL_SERVER)
    named = TTSConfig(provider=TTSProvider.LOCAL_SERVER, server_url=URL)

    assert await unset.validation_errors(settings) == ["SPEECH_BASE_URL missing"]
    assert await named.validation_errors(settings) == []


@pytest.fixture
def unasked(monkeypatch: pytest.MonkeyPatch) -> None:
    """The server at its address, not asked yet this process."""
    monkeypatch.setattr(library, "TRIED", set())
    monkeypatch.setattr(server, "LISTED", {})
    monkeypatch.setattr(settings, "SPEECH_BASE_URL", URL)


async def _listed() -> set[str]:
    """The server's voices as a listing has them once the ask it starts is in."""
    get_tts_voices()
    await asyncio.gather(*library.LOADING)
    return {v.id for v in get_tts_voices(TTSProvider.LOCAL_SERVER.value)}


@pytest.mark.parametrize(
    "listed",
    [
        {"voices": [{"id": "jf_alpha", "name": "jf_alpha"}], "default_voice": "x"},
        {"voices": ["jf_alpha", "af_heart"]},  # its legacy answer
    ],
)
async def test_a_listing_asks_the_server_for_its_voices_under_ids_of_their_own(
    unasked: None, monkeypatch: pytest.MonkeyPatch, listed: dict[str, Any]
) -> None:
    answering(monkeypatch, httpx.Response(200, json=listed))

    ids = await _listed()

    assert "local_server:jf_alpha" in ids
    assert len(ids) == len(server.VOICES) + 1  # the known ones once


async def test_a_server_not_running_yet_is_asked_again(
    unasked: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    answering(
        monkeypatch,
        httpx.Response(503),
        httpx.Response(200, json={"voices": ["jf_alpha"]}),
    )

    assert "local_server:jf_alpha" not in await _listed()
    assert "local_server:jf_alpha" in await _listed()


def test_a_voice_it_has_not_listed_yet_is_found_by_its_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A profile on one of its voices opens before any listing (a restart)."""
    monkeypatch.setattr(server, "LISTED", {})

    voice = get_voice("local_server:jf_alpha")

    assert voice is not None
    assert (voice.provider_id, voice.name) == ("local_server", "jf_alpha")
    assert speaking_model(voice.id, None) == "kokoro"
