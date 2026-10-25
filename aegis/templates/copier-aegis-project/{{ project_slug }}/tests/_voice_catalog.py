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
    """The running settings a profile writes (``profiles.SETTINGS``), put
    back after the test: switching or saving the active profile applies it
    to them."""
    from app.core.config import settings
    from app.services.ai.domains.voice import profiles

    for key in profiles.SETTINGS.values():
        monkeypatch.setattr(settings, key, getattr(settings, key))


async def only_profile(session: AsyncSession) -> Any:
    """One active voice profile, every other removed: alloy on tts-1."""
    from app.services.ai.domains.voice import profiles
    from app.services.ai.models.voice import VoiceProfile

    for row in await profiles.list_profiles(session):
        await session.delete(row)
    profile = VoiceProfile(
        name="Hers", is_active=True, tts_model="tts-1", tts_voice="alloy"
    )
    session.add(profile)
    await session.commit()
    return profile
