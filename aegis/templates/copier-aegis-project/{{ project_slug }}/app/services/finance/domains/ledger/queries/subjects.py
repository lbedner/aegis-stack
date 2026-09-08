"""Reads for subjects: whose money an account holds."""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import FinanceSubject


async def subjects_for_owner(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> list[FinanceSubject]:
    query = select(FinanceSubject).where(FinanceSubject.deleted_at.is_(None))
    if owner_user_id is not None:
        query = query.where(FinanceSubject.owner_user_id == owner_user_id)
    return list((await db.exec(query.order_by(FinanceSubject.name))).all())


async def subject_by_id(
    db: AsyncSession, subject_id: int, *, owner_user_id: int | None = None
) -> FinanceSubject | None:
    query = select(FinanceSubject).where(
        FinanceSubject.id == subject_id, FinanceSubject.deleted_at.is_(None)
    )
    if owner_user_id is not None:
        query = query.where(FinanceSubject.owner_user_id == owner_user_id)
    return (await db.exec(query)).first()
