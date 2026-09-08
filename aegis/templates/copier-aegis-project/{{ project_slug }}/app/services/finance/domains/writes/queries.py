"""Reads for the propose/approve queue."""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import FinancePendingChange


async def batch_rows(
    db: AsyncSession, batch_id: str, *, owner_user_id: int | None = None
) -> list[FinancePendingChange]:
    query = select(FinancePendingChange).where(
        FinancePendingChange.batch_id == batch_id
    )
    if owner_user_id is not None:
        query = query.where(FinancePendingChange.owner_user_id == owner_user_id)
    return list((await db.exec(query.order_by(FinancePendingChange.id))).all())  # type: ignore[arg-type]


async def get_change(
    db: AsyncSession, change_id: int, *, owner_user_id: int | None = None
) -> FinancePendingChange | None:
    row = (
        await db.exec(
            select(FinancePendingChange).where(FinancePendingChange.id == change_id)
        )
    ).first()
    if row is None:
        return None
    if owner_user_id is not None and row.owner_user_id != owner_user_id:
        return None
    return row


async def list_changes(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    status: str | None = "pending",
    proposed_by_agent: str | None = None,
) -> list[FinancePendingChange]:
    """Newest first. ``status=None`` returns the full audit trail;
    ``proposed_by_agent`` narrows to one proposer's cards, which is how an
    agent sees its own open work before filing more."""
    query = select(FinancePendingChange).order_by(
        FinancePendingChange.id.desc()  # type: ignore[attr-defined]
    )
    if status is not None:
        query = query.where(FinancePendingChange.status == status)
    if proposed_by_agent is not None:
        query = query.where(FinancePendingChange.proposed_by_agent == proposed_by_agent)
    if owner_user_id is not None:
        query = query.where(FinancePendingChange.owner_user_id == owner_user_id)
    return list((await db.exec(query)).all())
