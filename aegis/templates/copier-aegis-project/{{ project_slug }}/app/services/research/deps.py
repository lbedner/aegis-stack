"""FastAPI dependency provider for the research service, scoped to the
caller (``get_owner_user_id``): one owner never reads another's watches."""

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_async_db
from app.services.research.service import ResearchService
from app.services.shared.deps import get_owner_user_id


async def get_research_service(
    db: AsyncSession = Depends(get_async_db),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> ResearchService:
    return ResearchService(db, owner_user_id)
