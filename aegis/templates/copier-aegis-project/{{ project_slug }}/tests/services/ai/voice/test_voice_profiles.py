"""The voice and the call setup live in the database.

How the assistant sounds is a row the app changes (the voice profile), and
so is what a call runs on (the call setup), the way the active model is:
switching or editing either changes the next thing said, with no .env edit
and no restart. .env only seeds them. Picking a model changes the setup,
never the voice.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.domains.voice import profiles
from app.services.ai.models.voice import CallSetup, VoiceProfile


def _settings(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "STT_PROVIDER": "openai_whisper",
        "STT_MODEL": "gpt-transcribe",
        "TTS_PROVIDER": "openai",
        "TTS_MODEL": "gpt-4o-mini-tts-2025-03-20",
        "TTS_VOICE": "marin",
        "TTS_VOICES": {},
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
    # Each step reads the call setup once (as each request does); the
    # test takes 2 on purpose, so 3 would be one read too many.
    @pytest.mark.queryspy(threshold=3)
    async def test_the_first_voice_and_setup_are_whatever_env_says(
        self, async_db_session: AsyncSession
    ) -> None:
        seeded = await profiles.seed_from_settings(async_db_session, _settings())
        setup = await profiles.call_setup(async_db_session)

        assert seeded is not None and seeded.is_active
        assert seeded.voices == {"openai": "marin"}
        assert (seeded.tts_speed, seeded.tts_instructions) == (
            1.2,
            "Voice Affect: Warm.",
        )
        assert setup is not None
        assert (setup.tts_model, setup.stt_model, setup.live_engine) == (
            "gpt-4o-mini-tts-2025-03-20",
            "gpt-transcribe",
            "gpt-live",
        )

    # Seeds twice on purpose (that is the behaviour under test), then reads
    # the setup back: three reads of it; four would be an N+1.
    @pytest.mark.queryspy(threshold=4)
    async def test_seeding_never_touches_existing_rows(
        self, async_db_session: AsyncSession
    ) -> None:
        await profiles.seed_from_settings(async_db_session, _settings())
        again = await profiles.seed_from_settings(
            async_db_session, _settings(TTS_VOICE="nova", TTS_MODEL="tts-1")
        )

        assert again is None
        assert [p.voices for p in await profiles.list_profiles(async_db_session)] == [
            {"openai": "marin"}
        ]
        setup = await profiles.call_setup(async_db_session)
        assert setup is not None and setup.tts_model == "gpt-4o-mini-tts-2025-03-20"


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
            voices={"openai": "nova"},
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

    async def test_a_new_voice_sounds_like_the_active_one_designer_choices_too(
        self, async_db_session: AsyncSession
    ) -> None:
        seeded = await profiles.seed_from_settings(async_db_session, _settings())
        assert seeded is not None and seeded.id is not None
        await profiles.update(
            async_db_session, seeded.id, tts_delivery={"style": "warm"}
        )

        made = await profiles.create(async_db_session, name="Faster", tts_speed=1.4)

        assert made.tts_speed == 1.4
        assert made.voices == {"openai": "marin"}
        assert made.tts_delivery == {"style": "warm"}
        assert not made.is_active

    # Calls the same function twice on purpose (that is the behaviour under
    # test), so each of its reads runs exactly twice; three would be an N+1.
    @pytest.mark.queryspy(threshold=3)
    async def test_names_are_unique(self, async_db_session: AsyncSession) -> None:
        await profiles.seed_from_settings(async_db_session, _settings())
        await profiles.create(async_db_session, name="Faster")
        with pytest.raises(profiles.VoiceProfileError):
            await profiles.create(async_db_session, name="Faster")


class TestPickingAModel:
    """What a call runs on is the setup's: no pick changes how she sounds."""

    # Seeds, then makes three picks on purpose, each reading the setup once:
    # four reads of it; five would be an N+1.
    @pytest.mark.queryspy(threshold=5)
    async def test_speaking_hearing_and_calling_leave_the_voice_alone(
        self, async_db_session: AsyncSession
    ) -> None:
        settings = _settings()
        seeded = await profiles.seed_from_settings(async_db_session, settings)
        assert seeded is not None
        before = seeded.model_dump()

        await profiles.speak_with(async_db_session, settings, "kokoro")
        await profiles.hear_with(async_db_session, settings, "whisper-1")
        setup = await profiles.set_up(async_db_session, settings, live_engine="x")

        voice = await profiles.active_profile(async_db_session)
        assert voice is not None and voice.model_dump() == before
        assert (setup.tts_model, setup.stt_model, setup.live_engine) == (
            "kokoro",
            "whisper-1",
            "x",
        )

    # Seeds, then reads the setup back on purpose: two reads of it; three
    # would be an N+1.
    @pytest.mark.queryspy(threshold=3)
    async def test_a_voice_on_one_provider_keeps_the_others(
        self, async_db_session: AsyncSession
    ) -> None:
        seeded = await profiles.seed_from_settings(async_db_session, _settings())
        assert seeded is not None and seeded.id is not None

        setup = await profiles.call_setup(async_db_session)
        assert setup is not None
        spoken, _ = await profiles.give_voice(
            async_db_session, setup, seeded, "af_heart"
        )

        assert spoken.voices == {"openai": "marin", "kokoro": "af_heart"}


class TestApplying:
    """The setup and the voice land on the running settings, and the speech
    services, which read their config once, are dropped so the next call
    rebuilds."""

    def test_the_voice_on_the_setups_provider_is_the_one_spoken(self) -> None:
        settings = _settings()
        service = SimpleNamespace(_stt_service=object(), _tts_service=object())
        voice = VoiceProfile(
            name="Nova",
            voices={"openai": "nova", "kokoro": "af_heart"},
            tts_speed=1.0,
            tts_instructions=None,
        )
        setup = CallSetup(
            tts_provider="kokoro",
            tts_model="kokoro",
            reply="answer",
            working_sound="none",
        )

        profiles.apply(voice, settings, service, setup)

        assert (settings.TTS_VOICE, settings.TTS_MODEL, settings.TTS_SPEED) == (
            "af_heart",
            "kokoro",
            1.0,
        )
        assert settings.TTS_VOICES == {"openai": "nova", "kokoro": "af_heart"}
        assert settings.TTS_INSTRUCTIONS is None
        assert (settings.VOICE_REPLY, settings.VOICE_WORKING_SOUND) == (
            "answer",
            "none",
        )
        assert service._stt_service is None and service._tts_service is None

    def test_a_voice_with_none_on_the_provider_speaks_its_default(self) -> None:
        settings = _settings(TTS_PROVIDER="gemini")
        service = SimpleNamespace(_stt_service=None, _tts_service=None)

        profiles.apply(
            VoiceProfile(name="Hers", voices={"openai": "marin"}), settings, service
        )

        assert settings.TTS_VOICE is None


class TestAtStartup:
    async def test_a_fresh_install_runs_on_its_env_voice(
        self, async_db_session: AsyncSession
    ) -> None:
        settings = _settings()
        service = SimpleNamespace(_stt_service=None, _tts_service=None)

        active = await profiles.load_active(async_db_session, settings, service)

        assert active is not None and active.name == profiles.SEEDED_NAME
        assert settings.TTS_VOICE == "marin"

    # Seeds, changes the setup and loads on purpose, each reading the setup
    # once: three reads of it; four would be an N+1.
    @pytest.mark.queryspy(threshold=4)
    async def test_after_that_the_tables_win_over_env(
        self, async_db_session: AsyncSession
    ) -> None:
        await profiles.seed_from_settings(async_db_session, _settings())
        nova = await profiles.create(
            async_db_session, name="Nova", voices={"openai": "nova"}
        )
        await profiles.activate(async_db_session, nova.id)
        await profiles.set_up(async_db_session, _settings(), reply="answer")
        settings = _settings()  # .env still says marin, live
        service = SimpleNamespace(_stt_service=object(), _tts_service=object())

        await profiles.load_active(async_db_session, settings, service)

        assert (settings.TTS_VOICE, settings.VOICE_REPLY) == ("nova", "answer")
        assert service._tts_service is None


async def test_anything_headless_speaks_in_the_active_voice(
    async_db_session: AsyncSession,
) -> None:
    """A worker or the CLI never runs the webserver's startup, which puts
    the active profile on the settings: they read it here."""
    from app.core.config import settings

    assert await profiles.active_settings(async_db_session, settings) is settings
    async_db_session.add(
        VoiceProfile(
            name="Hers", is_active=True, voices={settings.TTS_PROVIDER: "nova"}
        )
    )
    await async_db_session.commit()

    spoken = await profiles.active_settings(async_db_session, settings)

    assert spoken.TTS_VOICE == "nova" and settings.TTS_VOICE != "nova"
