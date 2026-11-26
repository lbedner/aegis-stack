"""Which engine the voice speaks and listens through (``voice/engine_use``):
the speech or hearing server the inference component tracks."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import hearing_server, speech_server
from app.core.config import settings
from app.services.ai.domains.voice import engine_use


async def test_the_speech_server_speaks(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "TTS_PROVIDER", "local_server")
    monkeypatch.setattr(settings, "STT_PROVIDER", "openai_whisper")

    uses = await engine_use.voice_uses(async_db_session)

    assert [(u.engine, u.by) for u in uses] == [(speech_server.SLUG, "Voice, speaking")]


async def test_the_hearing_server_listens(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "TTS_PROVIDER", "openai")
    monkeypatch.setattr(settings, "STT_PROVIDER", "hearing_server")

    uses = await engine_use.voice_uses(async_db_session)

    assert [(u.engine, u.by) for u in uses] == [
        (hearing_server.SLUG, "Voice, listening")
    ]
