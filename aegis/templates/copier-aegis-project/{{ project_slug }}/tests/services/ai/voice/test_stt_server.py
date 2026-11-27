"""A hearing server you run (``stt/server.py``): any OpenAI-compatible
transcription server at HEARING_BASE_URL (speaches first), the way
Kokoro-FastAPI speaks at SPEECH_BASE_URL. The server is a stub; the real
client's requests are answered in the test."""

import httpx
import pytest

from app.core import speech_server
from app.core.config import Settings
from app.services.ai.domains.voice import get_stt_models, get_stt_providers
from app.services.ai.domains.voice.catalog import get_stt_model
from app.services.ai.domains.voice.models import (
    DEFAULT_STT_MODELS,
    AudioFormat,
    AudioInput,
    CannotRunError,
    STTProvider,
)
from app.services.ai.domains.voice.stt import STTConfig, get_stt_provider, server
from tests import _speech_server as speaking
from tests._speech_server import PARAKEET, SPEACHES, WHISPER, openai_answering, serving

URL = "http://localhost:8010/v1"


async def test_what_you_said_is_heard_by_the_server_at_its_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asked as OpenAI's transcription endpoint is, without the app's
    OpenAI key: the server is not OpenAI."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
    asked = openai_answering(
        monkeypatch, lambda: httpx.Response(200, json={"text": "What is in checking?"})
    )
    heard = get_stt_provider(STTProvider.HEARING_SERVER, server_url=URL)

    result = await heard.transcribe(
        AudioInput(content=b"RIFF....WAVE", format=AudioFormat.WAV)
    )

    [request] = asked
    assert str(request.url) == f"{URL}/audio/transcriptions"
    assert b"sk-real" not in request.headers.get("authorization", "").encode()
    assert DEFAULT_STT_MODELS[STTProvider.HEARING_SERVER].encode() in request.content
    assert result.text == "What is in checking?"


async def test_each_transcription_is_charted_for_its_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """How long it took (Overseer > Inference > speaches), on success only."""
    from app.core import hearing_server, series

    charted: list[dict[str, float]] = []

    async def record(points: dict[str, float]) -> None:
        charted.append(points)

    monkeypatch.setattr(series, "record", record)
    answers = iter([httpx.Response(200, json={"text": "Pay it."}), httpx.Response(400)])
    openai_answering(monkeypatch, lambda: next(answers))
    heard = get_stt_provider(STTProvider.HEARING_SERVER, server_url=URL)
    clip = AudioInput(content=b"RIFF....WAVE", format=AudioFormat.WAV)

    await heard.transcribe(clip)
    with pytest.raises(RuntimeError, match="Transcription failed"):
        await heard.transcribe(clip)

    assert [list(points) for points in charted] == [[hearing_server.LATENCY]]


def test_it_is_refused_until_its_address_is_set() -> None:
    with pytest.raises(CannotRunError, match="HEARING_BASE_URL"):
        get_stt_provider(STTProvider.HEARING_SERVER)


def test_it_is_a_local_hearing_provider_with_its_model() -> None:
    assert server.PROVIDER in get_stt_providers()
    assert server.PROVIDER.is_local
    assert [m.id for m in get_stt_models(server.PROVIDER.id)] == [
        DEFAULT_STT_MODELS[STTProvider.HEARING_SERVER]
    ]


def test_the_config_carries_the_hearing_servers_address() -> None:
    told = Settings(
        STT_PROVIDER="hearing_server",
        HEARING_BASE_URL="http://speaches:8000/v1",
    )
    config = STTConfig.from_settings(told)
    assert config.server_url == speech_server.reach(told, "HEARING_BASE_URL")
    assert config.server_url is not None


@pytest.mark.parametrize(
    ("speaking", "hearing", "why"),
    [
        ("http://kokoro:8880/v1", None, "HEARING_BASE_URL missing"),
        (None, URL, None),
    ],
)
def test_the_catalog_locks_it_on_its_own_address(
    monkeypatch: pytest.MonkeyPatch,
    speaking: str | None,
    hearing: str | None,
    why: str | None,
) -> None:
    """Checked against the speaking server's address, it was offered on a
    stack with Kokoro-FastAPI and none of its own, and its first call was
    refused."""
    from app.core.config import settings
    from app.services.ai.domains.voice.overview import blocked

    monkeypatch.setattr(settings, "SPEECH_BASE_URL", speaking)
    monkeypatch.setattr(settings, "HEARING_BASE_URL", hearing)
    assert blocked(server.PROVIDER, {}) == why


@pytest.fixture
def unasked(monkeypatch: pytest.MonkeyPatch) -> None:
    speaking.unasked(monkeypatch, server, "HEARING_BASE_URL", URL)


async def _listed() -> set[str]:
    return await speaking.listed(get_stt_models, STTProvider.HEARING_SERVER.value)


async def test_a_listing_asks_the_server_for_the_models_it_holds(
    unasked: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    serving(monkeypatch, SPEACHES)

    assert await _listed() == {PARAKEET, WHISPER}  # the known one once
    whisper = get_stt_model(WHISPER)
    assert whisper is not None and whisper.provider_id == server.PROVIDER_ID


async def test_a_hearing_server_not_running_yet_is_asked_again(
    unasked: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers: dict[str, object] = {"/v1/models": 503}
    serving(monkeypatch, answers)
    assert WHISPER not in await _listed()

    answers.update(SPEACHES)
    assert WHISPER in await _listed()
