"""Legs the user already categorised as a transfer."""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection import queries
from app.services.finance.models import (
    FinanceTransaction,
)
from app.services.shared.queries import owner_clause


async def _flag_category_transfers(
    db: AsyncSession, *, owner_user_id: int | None
) -> int:
    """Flag rows whose CATEGORY says transfer and that no pairing claimed.

    Pairing needs both legs, and the other leg often is not imported at
    all - a card payment where only the checking side syncs, a "Transfer
    Out" to an account the app has never seen. Measured live: $6,700 a
    month of rows the user's own categories called transfers, sitting in
    every spending figure because no counterpart ever arrived. The
    category classification is the user's own curation (Quicken paths
    fold into categories at import), so it outranks the absence of a pair.

    Runs AFTER pairing, so two legs that can pair get the full pairing.
    The trade-off is real and accepted: a leg flagged here is excluded
    from future pairing passes, so if its counterpart arrives in a later
    import the two stay unlinked - but the money math (out of spend, out
    of income) is already right, which is the job.

    Deliberately NO lookback, unlike pairing: deep history accumulates
    coincidental amount matches, but a classification is not a
    coincidence - it is what the row says it is, at any age, and the
    spending figures it inflates read months back. After the first pass
    only newly imported rows match, so the missing window costs nothing.

    ``transfer_group_id`` stays NULL: that column keeps meaning "paired",
    which is what lets a recategorize undo a category flag without ever
    dissolving a real pairing.
    """
    rows = await queries.transaction_rows_where(
        db,
        [
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
            FinanceTransaction.is_transfer.is_(False),
            FinanceTransaction.transfer_group_id.is_(None),
            FinanceTransaction.category_id.in_(queries.transfer_category_ids()),
            owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
        ],
    )
    for txn in rows:
        txn.is_transfer = True
        txn.excluded_from_reports = True
        db.add(txn)
    if rows:
        await db.flush()
    return len(rows)
