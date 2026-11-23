"""Which engine the voice speaks and listens through (``voice/engine_use``):
the speech server the inference component tracks, or a model in the app's
own process, in memory once it has loaded."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import speech_server
from app.core.config import settings
from app.services.ai.domains.voice import engine_use, local


@pytest.fixture(autouse=True)
def _nothing_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local, "LOADED", set())


async def test_the_speech_server_speaks(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "TTS_PROVIDER", "local_server")
    monkeypatch.setattr(settings, "STT_PROVIDER", "openai_whisper")

    uses, in_app = await engine_use.voice_uses(async_db_session)

    assert [(u.engine, u.by) for u in uses] == [(speech_server.SLUG, "Voice, speaking")]
    assert in_app == []


async def test_an_in_app_model_listens_and_says_when_it_is_in_memory(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "TTS_PROVIDER", "openai")
    monkeypatch.setattr(settings, "STT_PROVIDER", "parakeet")

    uses, in_app = await engine_use.voice_uses(async_db_session)
    local.LOADED.add("parakeet")
    _, loaded = await engine_use.voice_uses(async_db_session)

    assert [(u.engine, u.by) for u in uses] == [(speech_server.IN_APP, "Voice, listening")]
    assert [(e.name, e.loaded) for e in in_app] == [("Parakeet", False)]
    assert [(e.name, e.loaded) for e in loaded] == [("Parakeet", True)]


async def test_a_model_this_process_loaded_shows_though_the_voice_moved_on(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "TTS_PROVIDER", "openai")
    monkeypatch.setattr(settings, "STT_PROVIDER", "openai_whisper")
    local.LOADED.add("kokoro")

    _, in_app = await engine_use.voice_uses(async_db_session)

    assert [(e.name, e.loaded) for e in in_app] == [("Kokoro", True)]


def test_a_loader_records_its_provider_once_it_has_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def load() -> str:
        return "model"

    load.__module__ = "app.services.ai.domains.voice.tts.kokoro"
    model = local.loaded_once(load)

    assert local.LOADED == set()
    assert model() == "model"
    assert local.LOADED == {"kokoro"}


async def test_a_whisper_model_is_in_memory_once_it_has_transcribed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """faster-whisper keeps its model on its provider, not ``loaded_once``:
    the STT service records it once a transcription has run on it."""
    from app.services.ai.domains.voice.models import (
        AudioFormat,
        AudioInput,
        STTProvider,
        TranscriptionResult,
    )
    from app.services.ai.domains.voice.stt import STTService

    class Heard:
        provider_type = STTProvider.FASTER_WHISPER

        async def transcribe(self, audio: AudioInput) -> TranscriptionResult:
            return TranscriptionResult(text="hi", provider=STTProvider.FASTER_WHISPER)

    service = STTService(provider=STTProvider.FASTER_WHISPER)

    async def provider() -> Heard:
        return Heard()

    monkeypatch.setattr(service, "_get_provider", provider)
    await service.transcribe(AudioInput(content=b"x", format=AudioFormat.WAV))

    assert local.LOADED == {STTProvider.FASTER_WHISPER}
