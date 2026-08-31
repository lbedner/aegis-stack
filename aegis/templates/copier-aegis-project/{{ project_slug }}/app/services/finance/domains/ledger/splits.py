"""Splitting a transaction into category lines.

The parent row is never touched: its amount, category, payee and import
identity stay exactly as recorded, so re-imports still dedup and account
math still balances. A split only adds ``FinanceTransactionSplit`` child
rows and flips ``is_split``, which category reporting uses to swap the
parent for its lines.

Parts arrive as positive magnitudes (what the user actually knows: "the
food in it was $25") and the difference is filled automatically with a
remainder line inheriting the parent's own category.
"""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.ledger import queries
from app.services.finance.models import (
    FinanceTransaction,
    FinanceTransactionSplit,
)
from app.services.finance.schemas import SplitPart
from app.services.finance.utils import utcnow


async def _parent_or_raise(
    db: AsyncSession, transaction_id: int, owner_user_id: int | None
) -> FinanceTransaction:
    parent = await queries.transaction_by_id(
        db, transaction_id, owner_user_id=owner_user_id
    )
    if parent is None:
        raise ValueError(f"Transaction {transaction_id} not found.")
    return parent


async def split_transaction(
    db: AsyncSession,
    transaction_id: int,
    parts: list[SplitPart],
    *,
    owner_user_id: int | None = None,
) -> list[FinanceTransactionSplit]:
    """Carve a transaction into category lines, filling the difference.

    Replaces any existing lines (correcting a split never stacks), signs
    each magnitude to match the parent, and appends a remainder line under
    the parent's category when the parts leave money unclaimed. Raises
    ``ValueError`` on empty parts, non-positive magnitudes, or parts that
    exceed the parent's amount.
    """
    if not parts:
        raise ValueError("A split needs at least one part.")
    if any(part.amount <= 0 for part in parts):
        raise ValueError("Split parts must be positive magnitudes in minor units.")
    parent = await _parent_or_raise(db, transaction_id, owner_user_id)
    magnitude = abs(parent.amount)
    claimed = sum(part.amount for part in parts)
    if claimed > magnitude:
        raise ValueError(
            f"Split parts total {claimed} would exceed the transaction "
            f"amount {magnitude}."
        )

    existing = await queries.splits_for_parents(db, [transaction_id])
    for stale in existing.get(transaction_id, []):
        await db.delete(stale)
    await db.flush()

    lines: list[SplitPart] = list(parts)
    remainder = magnitude - claimed
    if remainder > 0:
        lines.append(SplitPart(amount=remainder, category_id=parent.category_id))

    sign = -1 if parent.amount < 0 else 1
    splits: list[FinanceTransactionSplit] = []
    for order, line in enumerate(lines):
        split = FinanceTransactionSplit(
            owner_user_id=parent.owner_user_id,
            parent_transaction_id=transaction_id,
            amount=sign * line.amount,
            category_id=line.category_id,
            memo=line.memo,
            sort_order=order,
            currency=parent.currency,
        )
        db.add(split)
        splits.append(split)

    parent.is_split = True
    parent.updated_at = utcnow()
    db.add(parent)
    await db.flush()
    return splits


async def unsplit_transaction(
    db: AsyncSession,
    transaction_id: int,
    *,
    owner_user_id: int | None = None,
) -> int:
    """Remove a transaction's split lines and clear the flag, returning
    how many lines were removed. The parent reverts to reporting under
    its own category, which was never touched."""
    parent = await _parent_or_raise(db, transaction_id, owner_user_id)
    existing = (await queries.splits_for_parents(db, [transaction_id])).get(
        transaction_id, []
    )
    for split in existing:
        await db.delete(split)
    parent.is_split = False
    parent.updated_at = utcnow()
    db.add(parent)
    await db.flush()
    return len(existing)
