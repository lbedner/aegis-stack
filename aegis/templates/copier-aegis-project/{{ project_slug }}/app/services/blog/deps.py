"""Blog dependencies for FastAPI route injection."""

from app.core.db import get_async_db
from app.services.blog.service import BlogService
from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession


async def get_blog_service(
    db: AsyncSession = Depends(get_async_db),
) -> BlogService:
    """Provide a BlogService instance."""
    return BlogService(db)
