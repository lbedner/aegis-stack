"""Meetings' scheduled jobs (``app.core.schedule``)."""

from app.core.db import get_async_session
from app.core.schedule import ServiceJob
from app.services.meetings.domains.calendar.service import read_calendars


async def read_agent_calendars_job() -> None:
    async with get_async_session() as session:
        await read_calendars(session)


JOBS: tuple[ServiceJob, ...] = (
    # Every minute: an invite reaches the feed within seconds, and an
    # agent is sent on time only if it is known before the start.
    ServiceJob(
        read_agent_calendars_job,
        "meetings_read_calendars",
        "Meetings: Read Agent Calendars",
        {"trigger": "interval", "minutes": 1},
    ),
)
