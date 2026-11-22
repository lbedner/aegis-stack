"""Reads over user accounts that count rather than list."""

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.visitor import GUEST_EMAIL
from app.models.user import User


async def member_count(db: AsyncSession) -> int:
    """Accounts other than the shared guest's: who has signed up."""
    result = await db.exec(
        select(func.count()).select_from(User).where(User.email != GUEST_EMAIL)
    )
    return result.one()
