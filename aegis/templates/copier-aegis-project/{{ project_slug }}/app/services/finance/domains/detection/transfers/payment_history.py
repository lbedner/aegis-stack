"""Card payments matched against the card's own history."""

from __future__ import annotations

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
    _flag_legs,
)


async def _pair_payment_history(db: AsyncSession, *, owner_user_id: int | None) -> int:
    """Pair card/loan payments across the FULL history, lookback be damned.

    The pairing lookback protects ordinary matching from coincidental
    amount collisions in deep history - correct there, but it left an
    entire Amex payment record unpaired (one pair out of three years,
    confirmed live), and the category phase's flag compounded it: flagged
    rows are excluded from pairing candidates, so history could NEVER
    pair. This phase is the carve-out, and its precision comes from the
    destination: an exact-amount, near-dated pair whose receiving side is
    a LIABILITY account is a payment, not a coincidence, at any age.

    Accepts legs the category phase already flagged (that is the point -
    it upgrades a lone flag into a real pair) as long as no transfer owns
    them yet. Always confirmed - the evidence bar here is higher than the
    scorer's own auto threshold.
    """
    acct_rows = await queries.account_rows_where(
        db,
        [
            FinanceAccount.deleted_at.is_(None),
            owner_clause(FinanceAccount.owner_user_id, owner_user_id),
        ],
    )
    liability_ids = {a.id for a in acct_rows if a.classification == "liability"}
    asset_ids = {a.id for a in acct_rows if a.classification != "liability"}
    if not liability_ids or not asset_ids:
        return 0

    def _unpaired(account_ids: set[int], inflow: bool) -> list:
        amount_clause = (
            FinanceTransaction.amount > 0 if inflow else FinanceTransaction.amount < 0
        )
        return [
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
            FinanceTransaction.transfer_group_id.is_(None),
            amount_clause,
            FinanceTransaction.account_id.in_(account_ids),
            owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
        ]

    inflows = await queries.transaction_rows_where(
        db, _unpaired(liability_ids, inflow=True)
    )
    if not inflows:
        return 0
    outflows = await queries.transaction_rows_where(
        db, _unpaired(asset_ids, inflow=False)
    )

    by_amount: dict[tuple[int, str], list[FinanceTransaction]] = {}
    for txn in outflows:
        by_amount.setdefault((abs(txn.amount), txn.currency), []).append(txn)

    paired = 0
    used: set[int] = set()
    for in_txn in sorted(inflows, key=lambda t: t.date_):
        candidates = [
            t
            for t in by_amount.get((in_txn.amount, in_txn.currency), [])
            if t.id not in used and abs((t.date_ - in_txn.date_).days) <= WINDOW_DAYS
        ]
        if not candidates:
            continue
        out_txn = min(candidates, key=lambda t: abs((t.date_ - in_txn.date_).days))
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
                    is_credit_card_payment=(
                        next(
                            (a for a in acct_rows if a.id == in_txn.account_id), None
                        ).account_type
                        == _CREDIT_CARD_TYPE
                        if any(a.id == in_txn.account_id for a in acct_rows)
                        else False
                    ),
                    match_method="payment_history",
                    confidence=AUTO_THRESHOLD,
                    status="confirmed",
                )
                db.add(transfer)
                await db.flush()
                _flag_legs(out_txn, in_txn, transfer.id)
                db.add(out_txn)
                db.add(in_txn)
                await db.flush()
        except IntegrityError:
            logger.debug("payment-history pairing skipped: leg already paired")
            continue
        used.add(out_txn.id)
        paired += 1
    return paired
