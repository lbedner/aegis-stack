"""The reads behind the agents' calendars."""

from datetime import datetime

from sqlalchemy import or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.models import CalendarEvent


async def events_of(
    db: AsyncSession,
    account_ids: list[int],
    start: datetime,
    end: datetime,
    keys: list[str],
) -> list[CalendarEvent]:
    """Those agents' kept meetings from ``start`` to ``end``, and any of
    ``keys`` wherever they were (one moved into the window)."""
    query = select(CalendarEvent).where(
        col(CalendarEvent.account_id).in_(account_ids),
        or_(
            col(CalendarEvent.starts_at).between(start, end),
            col(CalendarEvent.key).in_(keys),
        ),
    )
    return list((await db.exec(query)).all())
