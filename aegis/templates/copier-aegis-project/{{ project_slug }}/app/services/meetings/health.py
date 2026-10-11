"""Health check for meetings (dashboard ComponentStatus): how many meetings
across every owner, and how many the bot is in now."""

from app.core.db import get_async_session
from app.core.formatting import counted
from app.services.meetings.service import meetings_counts
from app.services.system.models import ComponentStatus, ComponentStatusType

MEETINGS_COMPONENT_NAME = "meetings"


async def check_meetings_service_health() -> ComponentStatus:
    async with get_async_session() as session:
        counts = await meetings_counts(session)
    return ComponentStatus(
        name=MEETINGS_COMPONENT_NAME,
        status=ComponentStatusType.HEALTHY,
        message=f"{counted(counts['meetings'], 'meeting')}, {counts['in_call']} in a call",
        metadata=counts,
    )
