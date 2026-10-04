"""Hearing and speaking cost money too.

Every transcription and every spoken reply was recorded at $0 (a TODO in
both services). Each is now priced at the catalog's rates and written to
the one usage ledger (``llm_usage``, action ``stt``/``tts``) beside the
model calls and live calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.core.db as db_module
from app.services.ai import usage_recording
from app.services.ai.domains.voice.stt import STTService
from app.services.ai.domains.voice.tts import TTSService
from app.services.ai.models.llm import LLMUsage
from tests._session import opens
from tests._voice_catalog import seed_voice_catalog


@pytest.fixture
async def ledger(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncSession:
    monkeypatch.setattr(db_module, "get_async_session", opens(async_db_session))
    monkeypatch.setattr(usage_recording, "get_async_session", opens(async_db_session))
    await seed_voice_catalog(async_db_session)
    return async_db_session


class TestRates:
    """Every rate is the catalog's: a model bills by the measures it lists."""

    @pytest.mark.parametrize(
        ("model", "measure", "cost"),
        [
            ("gpt-transcribe", {"input_seconds": 60}, 0.0045),
            ("gpt-4o-mini-transcribe", {"input_seconds": 60}, 0.003),
            ("tts-1", {"characters": 1_000_000}, 15.0),
            # Billed by the second of speech, not the character.
            ("gpt-4o-mini-tts", {"characters": 900, "output_seconds": 60}, 0.015),
            ("never-heard-of-it", {"input_seconds": 60}, 0.0),
        ],
    )
    @pytest.mark.asyncio
    async def test_a_measure_is_priced_by_its_model(
        self, ledger: AsyncSession, model: str, measure: dict[str, float], cost: float
    ) -> None:
        priced = await usage_recording.speech_cost(model, **measure)  # type: ignore[arg-type]
        assert priced == pytest.approx(cost)

    @pytest.mark.asyncio
    async def test_nothing_measured_costs_nothing(self, ledger: AsyncSession) -> None:
        assert await usage_recording.speech_cost("gpt-transcribe") == 0.0


def _settings(**values: object) -> MagicMock:
    settings = MagicMock()
    for key, value in values.items():
        setattr(settings, key, value)
    return settings


class TestHearing:
    @pytest.mark.asyncio
    async def test_a_transcription_is_priced_and_in_the_ledger(
        self, ledger: AsyncSession
    ) -> None:
        stt = STTService(
            _settings(
                STT_PROVIDER="openai_whisper",
                STT_MODEL="gpt-transcribe",
                STT_LANGUAGE=None,
                STT_DEVICE=None,
            )
        )
        await stt._record_usage(
            input_duration_seconds=30,
            latency_ms=900,
            user_id="0",
            success=True,
            error_message=None,
        )

        (row,) = (await ledger.exec(select(LLMUsage))).all()
        assert (row.action, row.model_id, row.audio_seconds) == (
            "stt",
            "gpt-transcribe",
            30,
        )
        assert row.total_cost == pytest.approx(0.00225)
        assert row.duration_ms == 900


class TestSpeaking:
    @pytest.mark.asyncio
    async def test_a_spoken_reply_is_priced_by_its_characters(
        self, ledger: AsyncSession
    ) -> None:
        tts = TTSService(
            _settings(
                TTS_PROVIDER="openai",
                TTS_MODEL="tts-1",
                TTS_VOICE="marin",
                TTS_SPEED=1.0,
                TTS_INSTRUCTIONS=None,
            )
        )
        await tts._record_usage(
            input_characters=2_000,
            output_duration_seconds=None,
            latency_ms=700,
            user_id="0",
            success=True,
            error_message=None,
        )

        (row,) = (await ledger.exec(select(LLMUsage))).all()
        assert (row.action, row.model_id) == ("tts", "tts-1")
        assert row.total_cost == pytest.approx(0.03)
