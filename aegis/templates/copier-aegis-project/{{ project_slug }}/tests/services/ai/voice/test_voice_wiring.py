"""A voice project can hear and speak for real.

The route tests patch ``ai_service``, so a service with no ``stt`` passed
them all.
"""

from app.core.config import settings
from app.services.ai.domains.voice import STTService, TTSService
from app.services.ai.service import AIService


def test_the_service_can_hear_and_speak() -> None:
    service = AIService(settings)

    assert isinstance(service.stt, STTService)
    assert isinstance(service.tts, TTSService)
    assert callable(service.voice_chat)
