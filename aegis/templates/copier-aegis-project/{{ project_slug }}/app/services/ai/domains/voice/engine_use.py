"""Which engine the voice speaks and listens through
(``chat/engine_users``): the speech or hearing server the inference
component tracks."""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import hearing_server, speech_server
from app.core.config import settings
from app.services.ai.domains.chat.engine_users import EngineUse
from app.services.ai.domains.voice import profiles
from app.services.ai.domains.voice.catalog import get_current_voice_config
from app.services.ai.domains.voice.models import STTProvider, TTSProvider

# The engine each server-run provider runs on.
SERVERS = {
    TTSProvider.LOCAL_SERVER: speech_server.SLUG,
    STTProvider.HEARING_SERVER: hearing_server.SLUG,
}


async def voice_uses(session: AsyncSession) -> list[EngineUse]:
    """What the active profile speaks and listens through."""
    used = await profiles.profile_settings(session, settings)
    config = get_current_voice_config(used)
    jobs = {config["tts_provider"]: "speaking", config["stt_provider"]: "listening"}
    return [
        EngineUse(engine=engine, by=f"Voice, {job}")
        for provider, job in jobs.items()
        if (engine := SERVERS.get(provider))
    ]
