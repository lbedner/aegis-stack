"""Removing a demo dataset without touching anything real.

Everything keys off the demo marker. Transfers are released before
their rows go, and insights are deleted by the accounts they name -
a foreign account in the way is reported, not deleted.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func
from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.ledger import networth
from app.services.finance.models import (
    FinanceAccount,
    FinanceBalanceSnapshot,
    FinanceHolding,
    FinanceImportBatch,
    FinanceImportBatchRow,
    FinanceInsight,
    FinanceLiabilityDetail,
    FinanceNetWorthSnapshot,
    FinancePendingChange,
    FinanceRecurringStream,
    FinanceTrade,
    FinanceTransaction,
    FinanceTransactionSplit,
    FinanceTransactionTag,
    FinanceTransfer,
    FinanceValuation,
)
from app.services.finance.seeds.demo_plan import (  # noqa: F401
    _DEFAULT_MONTHS,
    _SEED,
    PlannedSplit,
    PlannedTransaction,
    _day_in_month,
    _jitter,
    _month_starts,
    build_demo_ledger,
)
from app.services.finance.seeds.demo_seed.shared import (
    _demo_accounts,
    _is_demo,
    _seeded_window_start,
)


async def _delete_demo_rows(
    db: AsyncSession,
    owner_user_id: int | None,
    *,
    window_start: date | None = None,
) -> None:
    """Delete every row this module wrote for ``owner_user_id``.

    Scoped to the marked accounts and what hangs off them, so a user's own
    accounts, transactions, and imports survive untouched. Ordered to respect
    the foreign keys, including the circular transaction/transfer pair, whose
    back-references are cleared before their targets go.
    """
    accounts = await _demo_accounts(db, owner_user_id)
    if not accounts:
        return
    account_ids = [a.id for a in accounts]
    if window_start is None:
        window_start = await _seeded_window_start(db, account_ids)

    txns = list(
        (
            await db.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.account_id.in_(account_ids)
                )
            )
        ).all()
    )
    txn_ids = [t.id for t in txns]
    batch_ids = sorted(
        {t.import_batch_id for t in txns if t.import_batch_id is not None}
    )

    # Break the transaction <-> transfer/stream back-references first.
    for txn in txns:
        txn.transfer_group_id = None
        txn.transfer_pair_transaction_id = None
        txn.recurring_stream_id = None
        db.add(txn)
    await db.flush()

    if txn_ids:
        await _delete_where(
            db,
            FinanceTransactionSplit,
            FinanceTransactionSplit.parent_transaction_id,
            txn_ids,
        )
        await _delete_where(
            db, FinanceTransactionTag, FinanceTransactionTag.transaction_id, txn_ids
        )
    await _release_transfers(db, account_ids)
    # Insights point AT the rows below (a missed-payment insight names its
    # stream); an insight outliving its subject is a dangling claim, and
    # the FK refuses the delete while it stands.
    await _delete_insights_for(db, account_ids, txn_ids)
    await _delete_where(
        db, FinanceRecurringStream, FinanceRecurringStream.account_id, account_ids
    )
    if batch_ids:
        await _delete_where(
            db, FinanceImportBatchRow, FinanceImportBatchRow.import_batch_id, batch_ids
        )
    await _delete_where(
        db, FinanceTransaction, FinanceTransaction.account_id, account_ids
    )
    if batch_ids:
        await _delete_where(db, FinanceImportBatch, FinanceImportBatch.id, batch_ids)
    for model, column in (
        (FinanceValuation, FinanceValuation.account_id),
        (FinanceBalanceSnapshot, FinanceBalanceSnapshot.account_id),
        (FinanceHolding, FinanceHolding.account_id),
        (FinanceTrade, FinanceTrade.account_id),
        (FinanceLiabilityDetail, FinanceLiabilityDetail.account_id),
    ):
        await _delete_where(db, model, column, account_ids)
    # This owner's proposals that the seed filed, plus any card aimed at a
    # transaction that is going: a proposal outliving its subject points at
    # nothing. The owner clause keeps one household's clear from taking
    # another's in a multi-user install.
    owner_clause = (
        FinancePendingChange.owner_user_id.is_(None)
        if owner_user_id is None
        else FinancePendingChange.owner_user_id == owner_user_id
    )
    gone = set(txn_ids)
    proposal_ids = [
        p.id
        for p in (await db.exec(select(FinancePendingChange).where(owner_clause))).all()
        if p.proposed_by_agent == "demo_seed"
        or (p.payload or {}).get("transaction_id") in gone
    ]
    if proposal_ids:
        await _delete_where(
            db, FinancePendingChange, FinancePendingChange.id, proposal_ids
        )
    await _delete_where(db, FinanceAccount, FinanceAccount.id, account_ids)

    # Net-worth snapshots are per-owner, not per-account, so they can't be
    # scoped away like the rows above - the seeded accounts are baked into
    # each day's total. Drop the days the seed touched; they are derived, and
    # the caller recomputes them from whatever accounts remain.
    if window_start is not None:
        stale = (
            await db.exec(
                select(FinanceNetWorthSnapshot).where(
                    FinanceNetWorthSnapshot.as_of_date >= window_start,
                    FinanceNetWorthSnapshot.owner_user_id.is_(None)
                    if owner_user_id is None
                    else FinanceNetWorthSnapshot.owner_user_id == owner_user_id,
                )
            )
        ).all()
        for row in stale:
            await db.delete(row)
    await db.flush()


async def _release_transfers(db: AsyncSession, account_ids: list[int]) -> None:
    """Delete transfers touching these accounts, freeing every paired leg.

    A transfer can pair a seeded leg with one of the user's own transactions.
    Deleting the transfer without unflagging that surviving leg would leave a
    real transaction marked ``is_transfer`` and hidden from reports, pointing
    at a transfer that no longer exists.
    """
    transfers = list(
        (
            await db.exec(
                select(FinanceTransfer).where(
                    or_(
                        FinanceTransfer.from_account_id.in_(account_ids),
                        FinanceTransfer.to_account_id.in_(account_ids),
                    )
                )
            )
        ).all()
    )
    if not transfers:
        return
    leg_ids = {
        leg_id
        for transfer in transfers
        for leg_id in (transfer.from_transaction_id, transfer.to_transaction_id)
        if leg_id is not None
    }
    if leg_ids:
        legs = (
            await db.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.id.in_(sorted(leg_ids))
                )
            )
        ).all()
        for leg in legs:
            leg.is_transfer = False
            leg.excluded_from_reports = False
            leg.transfer_group_id = None
            leg.transfer_pair_transaction_id = None
            db.add(leg)
        await db.flush()
    for transfer in transfers:
        await db.delete(transfer)
    await db.flush()


async def _delete_insights_for(
    db: AsyncSession, account_ids: list[int], txn_ids: list[int]
) -> None:
    """Drop insights raised about rows this teardown is removing.

    An insight is a claim about a specific account, transaction, category,
    or stream, so it cannot outlive the row it describes - and the
    stream foreign key enforces that literally.
    """
    if not account_ids and not txn_ids:
        return
    conditions = []
    if account_ids:
        conditions.append(FinanceInsight.related_account_id.in_(account_ids))
    if txn_ids:
        conditions.append(FinanceInsight.related_transaction_id.in_(txn_ids))
    stream_ids = (
        [
            s.id
            for s in (
                await db.exec(
                    select(FinanceRecurringStream).where(
                        FinanceRecurringStream.account_id.in_(account_ids)
                    )
                )
            ).all()
            if s.id is not None
        ]
        if account_ids
        else []
    )
    if stream_ids:
        conditions.append(FinanceInsight.related_stream_id.in_(stream_ids))
    rows = (await db.exec(select(FinanceInsight).where(or_(*conditions)))).all()
    for row in rows:
        await db.delete(row)
    if rows:
        await db.flush()


async def _delete_where(
    db: AsyncSession, model: type, column: object, values: list[int]
) -> None:
    """Delete ``model`` rows whose ``column`` is in ``values``."""
    if not values:
        return
    rows = (await db.exec(select(model).where(column.in_(values)))).all()
    for row in rows:
        await db.delete(row)
    await db.flush()


async def count_foreign_accounts(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> int:
    """The owner's own (non-seeded) accounts.

    Seeding into an install that already holds real finance data is the one
    case worth a prompt: net-worth snapshots are per-owner aggregates, so the
    demo accounts get folded into the same daily totals as the real ones.
    Clearing afterwards recomputes those days from the accounts that remain,
    which is exact for accounts with a valuation series and lossy for
    provider-synced accounts that only carry a current balance.
    """
    query = select(FinanceAccount).where(FinanceAccount.deleted_at.is_(None))
    if owner_user_id is None:
        query = query.where(FinanceAccount.owner_user_id.is_(None))
    else:
        query = query.where(FinanceAccount.owner_user_id == owner_user_id)
    return len([a for a in (await db.exec(query)).all() if not _is_demo(a)])


async def clear_demo(db: AsyncSession, *, owner_user_id: int | None = None) -> int:
    """Remove the seeded dataset without rebuilding it. Returns accounts removed.

    The inverse of ``seed_demo``: pulls the demo data back out of an install
    that also holds real data. Writes; the caller commits.
    """
    accounts = await _demo_accounts(db, owner_user_id)
    if not accounts:
        return 0
    window_start = await _seeded_window_start(db, [a.id for a in accounts])
    # Net worth carries an account's earliest known balance BACKWARDS, so
    # the seed can leave snapshots on days before its own first
    # transaction. Widening the repair window to the oldest snapshot makes
    # sure none of those survive the clear, still reflecting accounts that
    # no longer exist.
    oldest_snapshot = (
        await db.exec(
            select(func.min(FinanceNetWorthSnapshot.as_of_date)).where(
                FinanceNetWorthSnapshot.owner_user_id.is_(None)
                if owner_user_id is None
                else FinanceNetWorthSnapshot.owner_user_id == owner_user_id
            )
        )
    ).first()
    if oldest_snapshot is not None:
        window_start = (
            oldest_snapshot
            if window_start is None
            else min(window_start, oldest_snapshot)
        )
    await _delete_demo_rows(db, owner_user_id, window_start=window_start)
    if window_start is not None:
        # Rebuild the days just dropped from whatever accounts survive, so a
        # user with real data keeps a truthful curve instead of a hole.
        await networth.recompute_snapshots(
            db, owner_user_id=owner_user_id, start_date=window_start
        )
    return len(accounts)
