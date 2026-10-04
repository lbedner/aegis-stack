"""The voice lives in the database.

How the assistant hears and speaks is a row the app changes, the way the
active model is: switching or editing it changes the next thing said, with
no .env edit and no restart. .env only seeds the first profile.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.domains.voice import profiles
from app.services.ai.models.voice import VoiceProfile


def _settings(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "STT_PROVIDER": "openai_whisper",
        "STT_MODEL": "gpt-transcribe",
        "TTS_PROVIDER": "openai",
        "TTS_MODEL": "gpt-4o-mini-tts-2025-03-20",
        "TTS_VOICE": "marin",
        "TTS_SPEED": 1.2,
        "TTS_INSTRUCTIONS": "Voice Affect: Warm.",
        "VOICE_REPLY": "live",
        "VOICE_WORKING_SOUND": "typing",
        "VOICE_LIVE_IDLE_SECONDS": 30,
        "VOICE_LIVE_ENGINE": "gpt-live",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestSeeding:
    async def test_the_first_profile_is_whatever_env_says(
        self, async_db_session: AsyncSession
    ) -> None:
        seeded = await profiles.seed_from_settings(async_db_session, _settings())

        assert seeded is not None and seeded.is_active
        assert (seeded.tts_voice, seeded.tts_model, seeded.tts_speed) == (
            "marin",
            "gpt-4o-mini-tts-2025-03-20",
            1.2,
        )
        assert seeded.stt_model == "gpt-transcribe"
        assert seeded.tts_instructions == "Voice Affect: Warm."

    # Calls the same function twice on purpose (that is the behaviour under
    # test), so each of its reads runs exactly twice; three would be an N+1.
    @pytest.mark.queryspy(threshold=3)
    async def test_seeding_never_touches_existing_profiles(
        self, async_db_session: AsyncSession
    ) -> None:
        await profiles.seed_from_settings(async_db_session, _settings())
        again = await profiles.seed_from_settings(
            async_db_session, _settings(TTS_VOICE="nova")
        )

        assert again is None
        assert [
            p.tts_voice for p in await profiles.list_profiles(async_db_session)
        ] == ["marin"]


class TestActivating:
    # Calls the same function twice on purpose (that is the behaviour under
    # test), so each of its reads runs exactly twice; three would be an N+1.
    @pytest.mark.queryspy(threshold=3)
    async def test_exactly_one_profile_is_active(
        self, async_db_session: AsyncSession
    ) -> None:
        first = await profiles.seed_from_settings(async_db_session, _settings())
        assert first is not None
        second = await profiles.create(
            async_db_session,
            name="Nova, plain",
            tts_voice="nova",
            tts_instructions=None,
        )

        await profiles.activate(async_db_session, second.id)

        active = await profiles.active_profile(async_db_session)
        assert active is not None and active.id == second.id
        assert [
            p.name
            for p in await profiles.list_profiles(async_db_session)
            if p.is_active
        ] == ["Nova, plain"]

    async def test_a_new_profile_starts_from_the_active_one(
        self, async_db_session: AsyncSession
    ) -> None:
        await profiles.seed_from_settings(async_db_session, _settings())
        made = await profiles.create(async_db_session, name="Faster", tts_speed=1.4)

        assert made.tts_speed == 1.4
        assert made.tts_voice == "marin"  # everything else copied
        assert not made.is_active

    # Calls the same function twice on purpose (that is the behaviour under
    # test), so each of its reads runs exactly twice; three would be an N+1.
    @pytest.mark.queryspy(threshold=3)
    async def test_names_are_unique(self, async_db_session: AsyncSession) -> None:
        await profiles.seed_from_settings(async_db_session, _settings())
        await profiles.create(async_db_session, name="Faster")
        with pytest.raises(profiles.VoiceProfileError):
            await profiles.create(async_db_session, name="Faster")


class TestApplying:
    """The profile lands on the running settings, and the speech services,
    which read their config once, are dropped so the next call rebuilds."""

    def test_a_profile_becomes_the_settings(self) -> None:
        settings = _settings()
        service = SimpleNamespace(_stt_service=object(), _tts_service=object())
        profile = VoiceProfile(
            name="Nova",
            stt_provider="openai_whisper",
            stt_model="gpt-transcribe",
            tts_provider="openai",
            tts_model="gpt-4o-mini-tts",
            tts_voice="nova",
            tts_speed=1.0,
            tts_instructions=None,
            reply="answer",
            working_sound="none",
        )

        profiles.apply(profile, settings, service)

        assert (settings.TTS_VOICE, settings.TTS_MODEL, settings.TTS_SPEED) == (
            "nova",
            "gpt-4o-mini-tts",
            1.0,
        )
        assert settings.TTS_INSTRUCTIONS is None
        assert (settings.VOICE_REPLY, settings.VOICE_WORKING_SOUND) == (
            "answer",
            "none",
        )
        assert service._stt_service is None and service._tts_service is None


class TestAtStartup:
    async def test_a_fresh_install_runs_on_its_env_voice(
        self, async_db_session: AsyncSession
    ) -> None:
        settings = _settings()
        service = SimpleNamespace(_stt_service=None, _tts_service=None)

        active = await profiles.load_active(async_db_session, settings, service)

        assert active is not None and active.name == profiles.SEEDED_NAME
        assert settings.TTS_VOICE == "marin"

    # Calls the same function twice on purpose (that is the behaviour under
    # test), so each of its reads runs exactly twice; three would be an N+1.
    @pytest.mark.queryspy(threshold=3)
    async def test_after_that_the_table_wins_over_env(
        self, async_db_session: AsyncSession
    ) -> None:
        await profiles.seed_from_settings(async_db_session, _settings())
        nova = await profiles.create(async_db_session, name="Nova", tts_voice="nova")
        await profiles.activate(async_db_session, nova.id)
        settings = _settings()  # .env still says marin
        service = SimpleNamespace(_stt_service=object(), _tts_service=object())

        await profiles.load_active(async_db_session, settings, service)

        assert settings.TTS_VOICE == "nova"
        assert service._tts_service is None
