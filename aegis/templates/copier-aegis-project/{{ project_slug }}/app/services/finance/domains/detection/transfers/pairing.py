"""Pairing two legs of the same move across accounts."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.services.finance.domains.detection import queries
from app.services.finance.models import (
    FinanceAccount,
    FinanceTransaction,
    FinanceTransfer,
)
from app.services.shared.queries import owner_clause

from .shared import (
    _CREDIT_CARD_TYPE,
    AUTO_THRESHOLD,
    WINDOW_DAYS,
    TransferDetectionResult,
    _flag_legs,
    _score,
    _within_band,
)


async def _pair_transfers(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    today: date,
    lookback_days: int,
) -> TransferDetectionResult:
    """The pairing pass: score and link opposite legs (see module doc)."""
    result = TransferDetectionResult()

    acct_filters = [
        FinanceAccount.deleted_at.is_(None),
        owner_clause(FinanceAccount.owner_user_id, owner_user_id),
    ]
    accounts = await queries.account_rows_where(db, acct_filters)
    account_type = {a.id: a.account_type for a in accounts}
    if not account_type:
        return result

    # Legs already claimed by a transfer (any status) — excluded so pairings
    # (including rejected ones) never recur.
    paired_ids = await queries.claimed_leg_ids(db, owner_user_id)

    txn_filters = [
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.dedup_status != "duplicate",
        FinanceTransaction.is_transfer.is_(False),
        FinanceTransaction.transfer_group_id.is_(None),
        FinanceTransaction.account_id.in_(list(account_type.keys())),
        owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
    ]
    if lookback_days:
        txn_filters.append(
            FinanceTransaction.date_ >= today - timedelta(days=lookback_days)
        )
    txns = await queries.transaction_rows_where(db, txn_filters)
    candidates = [t for t in txns if t.id not in paired_ids]

    outflows = [t for t in candidates if t.amount < 0]
    inflows = [t for t in candidates if t.amount > 0]
    if not outflows or not inflows:
        return result

    # Score every plausible (outflow, inflow) pair, then greedily take the
    # highest-confidence pairs so each leg is used at most once per pass.
    scored: list[tuple[int, bool, FinanceTransaction, FinanceTransaction]] = []
    for out_txn in outflows:
        for in_txn in inflows:
            if out_txn.account_id == in_txn.account_id:
                continue  # a transfer moves between DIFFERENT accounts
            if out_txn.currency != in_txn.currency:
                continue  # $500 out and CA$500 in are not the same money
            if not _within_band(out_txn.amount, in_txn.amount):
                continue
            if abs((out_txn.date_ - in_txn.date_).days) > WINDOW_DAYS:
                continue
            in_on_card = account_type.get(in_txn.account_id) == _CREDIT_CARD_TYPE
            score, is_ccp = _score(out_txn, in_txn, in_on_card=in_on_card)
            if score >= AUTO_THRESHOLD:
                scored.append((score, is_ccp, out_txn, in_txn))

    scored.sort(key=lambda entry: entry[0], reverse=True)

    used: set[int] = set()
    for score, is_ccp, out_txn, in_txn in scored:
        if out_txn.id in used or in_txn.id in used:
            continue
        try:
            async with db.begin_nested():
                transfer = FinanceTransfer(
                    owner_user_id=owner_user_id,
                    organization_id=out_txn.organization_id,
                    from_account_id=out_txn.account_id,
                    to_account_id=in_txn.account_id,
                    from_transaction_id=out_txn.id,
                    to_transaction_id=in_txn.id,
                    amount=abs(out_txn.amount),
                    currency=out_txn.currency,
                    transfer_date=out_txn.date_,
                    is_credit_card_payment=is_ccp,
                    match_method="auto_amount_date",
                    confidence=score,
                    status="confirmed",
                )
                db.add(transfer)
                await db.flush()
                _flag_legs(out_txn, in_txn, transfer.id)
                db.add(out_txn)
                db.add(in_txn)
                await db.flush()
        except IntegrityError:
            # A leg was claimed by another transfer (race / prior pass). The
            # partial-uniques guarantee one transfer per leg — skip this pair.
            logger.debug("transfer pairing skipped: leg already paired")
            continue
        used.add(out_txn.id)
        used.add(in_txn.id)
        result.auto_paired += 1
    return result
