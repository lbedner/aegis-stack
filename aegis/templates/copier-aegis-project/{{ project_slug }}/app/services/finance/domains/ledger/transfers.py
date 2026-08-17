"""Transfers: pairing confirmation and rejection.

Read statements live in ``ledger/queries.py``; this module owns writes and
orchestration and delegates every fetch.
"""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.ledger import queries
from app.services.finance.models import (
    FinanceTransfer,
)


async def get_transfer(
    db: AsyncSession, transfer_id: int, *, owner_user_id: int | None
) -> FinanceTransfer | None:
    return await queries.transfer_by_id(db, transfer_id, owner_user_id=owner_user_id)


async def list_transfers(
    db: AsyncSession, *, owner_user_id: int | None = None, status: str | None = None
) -> list[FinanceTransfer]:
    """Transfers for an owner (optionally one ``status``), newest first."""
    return await queries.transfers_for_owner(
        db, owner_user_id=owner_user_id, status=status
    )


async def confirm_transfer(
    db: AsyncSession, transfer_id: int, *, owner_user_id: int | None = None
) -> FinanceTransfer | None:
    """Confirm a suggested transfer: flip to ``confirmed`` and flag both
    legs out of reports + cross-link them. Returns None if not found for
    this owner."""
    transfer = await get_transfer(db, transfer_id, owner_user_id=owner_user_id)
    if transfer is None:
        return None
    transfer.status = "confirmed"
    db.add(transfer)
    leg_ids = [
        txn_id
        for txn_id in (transfer.from_transaction_id, transfer.to_transaction_id)
        if txn_id is not None
    ]
    legs_by_id = await queries.transactions_by_ids(db, leg_ids)
    legs = [legs_by_id[txn_id] for txn_id in leg_ids if txn_id in legs_by_id]
    for leg in legs:
        leg.is_transfer = True
        leg.excluded_from_reports = True
        leg.transfer_group_id = transfer.id
        db.add(leg)
    if len(legs) == 2:
        legs[0].transfer_pair_transaction_id = legs[1].id
        legs[1].transfer_pair_transaction_id = legs[0].id
    await db.flush()
    return transfer


async def reject_transfer(
    db: AsyncSession, transfer_id: int, *, owner_user_id: int | None = None
) -> FinanceTransfer | None:
    """Reject a transfer: mark ``rejected`` and restore both legs to normal
    spend/income. The row persists so the pair is never re-suggested."""
    transfer = await get_transfer(db, transfer_id, owner_user_id=owner_user_id)
    if transfer is None:
        return None
    transfer.status = "rejected"
    db.add(transfer)
    leg_ids = [
        txn_id
        for txn_id in (transfer.from_transaction_id, transfer.to_transaction_id)
        if txn_id is not None
    ]
    legs_by_id = await queries.transactions_by_ids(db, leg_ids)
    for leg in legs_by_id.values():
        if leg.transfer_group_id == transfer.id:
            leg.is_transfer = False
            leg.excluded_from_reports = False
            leg.transfer_group_id = None
            leg.transfer_pair_transaction_id = None
            db.add(leg)
    await db.flush()
    return transfer
