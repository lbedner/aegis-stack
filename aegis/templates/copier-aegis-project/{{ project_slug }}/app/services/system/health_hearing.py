"""The hearing server the inference component tracks, as a health status:
up or down, and the hearing models it holds and has in memory. It rides
the inference check (``health_inference``) as a sub-component, so
``health``, ``/health/detailed`` and the map carry it with the text engine.
"""

from app.core import hearing_server
from app.core.config import settings
from app.core.formatting import counted
from app.core.hearing_server import HearingServerReading

from .models import ComponentStatus, ComponentStatusType


def _said(reading: HearingServerReading) -> tuple[ComponentStatusType, str]:
    """The status a reading is, and the line that says it: idle (none in
    memory) is information, not a fault, since the first call loads one."""
    if not reading.available:
        return ComponentStatusType.UNHEALTHY, "Hearing server not reachable"
    if not reading.models:
        return ComponentStatusType.WARNING, "Hearing server running but holds no models"
    held = f"{hearing_server.NAME} • {counted(len(reading.models), 'model')}"
    if reading.loaded is None:
        return ComponentStatusType.HEALTHY, held
    if not reading.loaded:
        return ComponentStatusType.INFO, f"{held} • none in memory"
    return ComponentStatusType.HEALTHY, f"{held} • {len(reading.loaded)} in memory"


async def check_hearing_health() -> ComponentStatus | None:
    """The hearing server at HEARING_BASE_URL now, as a health status; None
    where none is set."""
    url = hearing_server.reach(settings)
    if url is None:
        return None
    reading = await hearing_server.read(url)
    status, message = _said(reading)
    return ComponentStatus(
        name=hearing_server.SLUG,
        status=status,
        message=message,
        response_time_ms=None,
        metadata=reading,
    )
