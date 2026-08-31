"""Reads for split transactions: the lines a parent carries."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import FinanceTransactionSplit


async def splits_for_parents(
    db: AsyncSession, parent_ids: Iterable[int]
) -> dict[int, list[FinanceTransactionSplit]]:
    """All split rows for the given parent transactions, one query,
    grouped by parent id, in line order."""
    wanted = set(parent_ids)
    if not wanted:
        return {}
    rows = (
        await db.exec(
            select(FinanceTransactionSplit)
            .where(FinanceTransactionSplit.parent_transaction_id.in_(wanted))
            .order_by(
                FinanceTransactionSplit.parent_transaction_id,
                FinanceTransactionSplit.sort_order,
            )
        )
    ).all()
    grouped: dict[int, list[FinanceTransactionSplit]] = defaultdict(list)
    for split in rows:
        grouped[split.parent_transaction_id].append(split)
    return dict(grouped)
