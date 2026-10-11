"""FastAPI dependency provider for the meetings service, scoped to the
caller (``get_owner_user_id``): one owner never reads another's meetings."""

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_async_db
from app.services.meetings.service import MeetingsService
from app.services.shared.deps import get_owner_user_id


async def get_meetings_service(
    db: AsyncSession = Depends(get_async_db),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> MeetingsService:
    return MeetingsService(db, owner_user_id)
