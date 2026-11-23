"""The catalog's voice models, for tests that price or dial them.

Seeded from the catalog's own offline seed (``fixtures/llm_catalog``), so
a test prices at exactly the rates a fresh install would. Idempotent: the
seed skips what is already there.
"""

from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.fixtures.llm_fixtures import load_all_llm_fixtures


async def seed_voice_catalog(session: AsyncSession) -> None:
    """The offline catalog, voice models and their prices included."""
    await session.run_sync(load_all_llm_fixtures)
    await session.commit()


def keep_voice_settings(monkeypatch: Any) -> None:
    """The running settings the call setup and a voice write
    (``profiles.SETUP``, ``profiles.VOICE``, and the voice spoken), put
    back after the test: switching or saving either applies it to them."""
    from app.core.config import settings
    from app.services.ai.domains.voice import profiles

    for key in (*profiles.SETUP.values(), *profiles.VOICE.values(), "TTS_VOICE"):
        monkeypatch.setattr(settings, key, getattr(settings, key))


async def no_voices(session: AsyncSession) -> None:
    """Every voice profile and the call setup gone, unread: a test's own
    reads are the ones it counts."""
    from sqlalchemy import delete

    from app.services.ai.models.voice import CallSetup, VoiceProfile

    for table in (VoiceProfile, CallSetup):
        await session.exec(delete(table))  # type: ignore[call-overload]
    await session.commit()


async def only_profile(session: AsyncSession) -> Any:
    """One active voice profile, every other removed: alloy on OpenAI, the
    call setup speaking on tts-1."""
    from app.services.ai.models.voice import CallSetup, VoiceProfile

    await no_voices(session)
    session.add(CallSetup(tts_provider="openai", tts_model="tts-1"))
    profile = VoiceProfile(name="Hers", is_active=True, voices={"openai": "alloy"})
    session.add(profile)
    await session.commit()
    return profile
