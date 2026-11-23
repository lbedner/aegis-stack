"""Which engine the voice speaks and listens through
(``chat/engine_users``): the speech server the inference component tracks,
or a model loaded into the app's own process."""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import speech_server
from app.core.config import settings
from app.services.ai.domains.chat.engine_users import EngineUse, InAppEngine
from app.services.ai.domains.voice import local, profiles
from app.services.ai.domains.voice.catalog import (
    get_current_voice_config,
    get_stt_providers,
    get_tts_providers,
)
from app.services.ai.domains.voice.models import LOCAL_PACKAGES, TTSProvider


async def voice_uses(
    session: AsyncSession,
) -> tuple[list[EngineUse], list[InAppEngine]]:
    """What the active profile speaks and listens through, and each in-app
    engine it uses or this process has loaded."""
    used = await profiles.profile_settings(session, settings)
    config = get_current_voice_config(used)
    jobs = {config["tts_provider"]: "speaking", config["stt_provider"]: "listening"}
    names = {p.id: p.name for p in (*get_tts_providers(), *get_stt_providers())}
    uses = [
        EngineUse(engine=engine, by=f"Voice, {job}")
        for provider, job in jobs.items()
        if (engine := _engine(provider))
    ]
    in_app = [
        InAppEngine(name=names.get(provider, provider), loaded=provider in local.LOADED)
        for provider in LOCAL_PACKAGES
        if provider in jobs or provider in local.LOADED
    ]
    return uses, in_app


def _engine(provider: str) -> str | None:
    """The engine a voice provider runs on, where it is a local one."""
    if provider == TTSProvider.LOCAL_SERVER:
        return speech_server.SLUG
    return speech_server.IN_APP if provider in LOCAL_PACKAGES else None
