"""What a live call is made of, as the voice dialog shows it
(``call_setup``): what hears the caller and what speaks the answer (the
active voice's own models), where each runs, and what the call costs a
minute, every part added up."""

from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.services.ai.domains.spend import recording as usage_recording
from app.services.ai.domains.voice import call_setup
from app.services.ai.models.voice import VoiceProfile
from tests._session import opens
from tests._voice_catalog import seed_voice_catalog


def _voice(**columns: Any) -> VoiceProfile:
    return VoiceProfile(
        **{
            "name": "Marin",
            "stt_provider": "openai_whisper",
            "stt_model": "gpt-transcribe",
            "tts_provider": "openai",
            "tts_model": "gpt-4o-mini-tts-2025-03-20",
            "tts_voice": "marin",
            "tts_speed": 1.2,
            **columns,
        }
    )


def _local_voice() -> VoiceProfile:
    return _voice(
        stt_provider="faster_whisper",
        stt_model="large-v3",
        tts_provider="kokoro",
        tts_model="kokoro-v1.0",
    )


def test_it_names_what_hears_and_what_speaks_and_where_each_runs() -> None:
    cloud, local = _voice(), _local_voice()

    assert call_setup.hears(cloud, settings) == call_setup.Part(
        "gpt-transcribe", local=False, model="gpt-transcribe"
    )
    assert call_setup.speaks(cloud, settings) == call_setup.Part(
        "gpt-4o-mini-tts-2025-03-20 · Marin",
        local=False,
        note="1.2×",
        model="gpt-4o-mini-tts-2025-03-20",
    )
    assert call_setup.hears(local, settings).local
    assert call_setup.speaks(local, settings).name == "Kokoro v1.0 · Marin"


@pytest.fixture
async def priced(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(usage_recording, "get_async_session", opens(async_db_session))
    await seed_voice_catalog(async_db_session)


@pytest.mark.usefixtures("priced")
class TestTheSummary:
    async def test_all_on_this_machine_is_free(self) -> None:
        said = await call_setup.chain_summary(
            _local_voice(), settings, thinks_local=True, wait_ms=1400
        )

        assert said == call_setup.Summary(
            "Runs entirely on this machine", True, "free", "about 1.4s to first word"
        )

    async def test_cloud_speech_is_added_up_by_the_minute(self) -> None:
        """Up to a minute heard and a minute said in each minute of call,
        at the catalog's rates: the local model is free, the call is not."""
        said = await call_setup.chain_summary(
            _voice(tts_model="tts-1"), settings, thinks_local=True, wait_ms=None
        )

        assert said.where == "Hears and speaks in the cloud"
        assert not said.local
        # gpt-transcribe $0.0045 a minute heard; tts-1 by the character,
        # a minute's worth ($0.0135)
        assert said.cost == "up to $0.02 a minute"
        assert said.wait == "no calls timed yet"

    async def test_a_cloud_part_with_no_rate_leaves_the_cost_unknown(
        self,
    ) -> None:
        """Priced by its tokens only, a minute of it cannot be costed: the
        call is not cheaper for it."""
        said = await call_setup.chain_summary(
            _voice(), settings, thinks_local=True, wait_ms=None
        )

        assert said.cost == "price unknown"

    async def test_one_model_is_its_own_rate(self) -> None:
        """A realtime model hears and speaks itself: its call is its rate,
        by the minute where it bills by time, else by its tokens."""
        by_time = await call_setup.one_summary("gpt-live-1", "openai", wait_ms=900)
        by_tokens = await call_setup.one_summary(
            "gpt-realtime-2.1", "openai", wait_ms=None
        )

        assert by_time == call_setup.Summary(
            "Runs in the cloud (OpenAI)",
            False,
            "$0.05 a minute",
            "about 0.9s to first word",
        )
        assert by_tokens.cost == "priced by its tokens"
