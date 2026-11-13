"""``ai speak`` saves the speech in the format it came back in: the default
OpenAI model answers in WAV, and a WAV named .mp3 plays nowhere."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.cli.ai import speech
from app.services.ai.domains.voice.models import AudioFormat, SpeechResult, TTSProvider
from tests._cli import invoke


def test_speak_names_the_file_by_what_came_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    service = MagicMock()
    service.tts.synthesize = AsyncMock(
        return_value=SpeechResult(
            audio=b"RIFF", format=AudioFormat.WAV, provider=TTSProvider.OPENAI
        )
    )
    monkeypatch.setattr("app.services.ai.service.AIService", lambda _: service)
    monkeypatch.setattr(speech, "speaking_settings", AsyncMock(return_value=None))

    result = invoke(["ai", "speak", "Hello"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "speech.wav").read_bytes() == b"RIFF"


def test_tts_status_says_its_providers_voices_and_what_it_lacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    served = settings.model_copy(
        update={"TTS_PROVIDER": "local_server", "SPEECH_BASE_URL": None}
    )
    monkeypatch.setattr(speech, "speaking_settings", AsyncMock(return_value=served))

    result = invoke(["ai", "tts-status"])

    assert result.exit_code == 0, result.output
    assert "bm_george" in result.output  # one of its voices, not the one in use
    assert "shimmer" not in result.output
    assert "SPEECH_BASE_URL missing" in result.output
