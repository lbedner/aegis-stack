"""Reads for confirmed transfer pairs."""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import (
    FinanceTransfer,
)


async def transfer_by_id(
    db: AsyncSession, transfer_id: int, *, owner_user_id: int | None = None
) -> FinanceTransfer | None:
    query = select(FinanceTransfer).where(FinanceTransfer.id == transfer_id)
    if owner_user_id is not None:
        query = query.where(FinanceTransfer.owner_user_id == owner_user_id)
    return (await db.exec(query)).first()


async def transfers_for_owner(
    db: AsyncSession, *, owner_user_id: int | None = None, status: str | None = None
) -> list[FinanceTransfer]:
    """Transfers for an owner (optionally one status), newest first."""
    query = select(FinanceTransfer)
    if owner_user_id is not None:
        query = query.where(FinanceTransfer.owner_user_id == owner_user_id)
    if status is not None:
        query = query.where(FinanceTransfer.status == status)
    query = query.order_by(
        FinanceTransfer.transfer_date.desc(), FinanceTransfer.id.desc()
    )
    return list((await db.exec(query)).all())
