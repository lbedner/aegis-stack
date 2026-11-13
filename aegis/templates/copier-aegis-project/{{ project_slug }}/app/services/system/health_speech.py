"""The speech server the inference component tracks, as a health status:
up or down, and the voices and models it lists. It rides the inference
check (``health_ollama``) as a sub-component, so ``health``,
``/health/detailed`` and the map carry it with Ollama.
"""

from app.core import speech_server
from app.core.config import settings
from app.core.formatting import counted
from app.core.speech_server import SpeechServerReading

from .models import ComponentStatus, ComponentStatusType

SPEECH = "speech"


def speech_status(reading: SpeechServerReading) -> ComponentStatus:
    """A reading as a health status."""
    if not reading.available:
        status, message = ComponentStatusType.UNHEALTHY, "Speech server not reachable"
    elif not reading.voices:
        status = ComponentStatusType.WARNING
        message = "Speech server running but lists no voices"
    else:
        status = ComponentStatusType.HEALTHY
        message = f"{speech_server.NAME} • {counted(len(reading.voices), 'voice')}"
    return ComponentStatus(
        name=SPEECH,
        status=status,
        message=message,
        response_time_ms=None,
        metadata=reading,
    )


async def check_speech_health() -> ComponentStatus | None:
    """The speech server at SPEECH_BASE_URL now; None where none is set."""
    url = speech_server.reach(settings)
    return speech_status(await speech_server.read(url)) if url else None
