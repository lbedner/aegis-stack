"""Internal-transfer detection + pairing (FIN-26).

Kills the #1 aggregator bug: money moved between a user's own accounts (a
credit-card payment, a checking->savings sweep) counted as spending on the
outflow side while never netting out. This pairs the two legs and flags them
out of spend/income reports.

Run after each sync/import batch. High-confidence matches (>= ``AUTO_THRESHOLD``)
auto-pair and are hidden from reports; medium matches (``SUGGEST_THRESHOLD`` up
to auto) are recorded as ``status='suggested'`` for the user to confirm. We
NEVER hide money below the auto threshold: a Venmo to a friend looks like a
transfer but is real spending. A transaction is a leg of at most one transfer
(DB partial-uniques on both legs); an existing transfer row — including a
``rejected`` one — keeps that pairing from recurring.

Scoring note: the design brief's candidate rule ("within $2") contradicts its
own near-miss acceptance ($1,900 vs $1,850). We widen the candidate band to
``max($2, 5%)`` so near-misses are considered, reserve the full amount score
for an exact ("within $2") match, and give a within-band-but-inexact match a
partial score. Net effect: exact same-day moves auto-pair; fuzzy ones surface
as suggestions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import re

from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.services.finance.models import (
    FinanceAccount,
    FinanceTransaction,
    FinanceTransfer,
)

WINDOW_DAYS = 5
AMOUNT_EXACT_TOLERANCE_CENTS = 200  # $2 fee tolerance -> full amount score
AMOUNT_BAND_PCT = 0.05  # within 5% (or $2) is a candidate at all
AUTO_THRESHOLD = 80
SUGGEST_THRESHOLD = 50
_CREDIT_CARD_TYPE = "credit_card"
_PAYEE_RE = re.compile(r"PAYMENT|PYMT|TRANSFER|XFER|EPAY|AUTOPAY|ACH", re.IGNORECASE)


@dataclass
class TransferDetectionResult:
    """Counts from one detection pass."""

    auto_paired: int = 0
    suggested: int = 0


def _owner_clause(column, owner_user_id: int | None):
    """Scan the owner's rows; a NULL owner (standalone, no auth) uses IS NULL."""
    return column.is_(None) if owner_user_id is None else column == owner_user_id


def _within_band(out_amount: int, in_amount: int) -> bool:
    """Whether two legs are close enough in magnitude to be a transfer pair."""
    diff = abs(abs(out_amount) - abs(in_amount))
    band = max(AMOUNT_EXACT_TOLERANCE_CENTS, abs(out_amount) * AMOUNT_BAND_PCT)
    return diff <= band


def _score(
    out_txn: FinanceTransaction, in_txn: FinanceTransaction, *, in_on_card: bool
) -> tuple[int, bool]:
    """Confidence 0-100 and whether the credit-card-payment rule fired."""
    score = 0
    if abs(abs(out_txn.amount) - abs(in_txn.amount)) <= AMOUNT_EXACT_TOLERANCE_CENTS:
        score += 40  # exact (within the fee tolerance)
    else:
        score += 25  # within band, but not exact
    delta = abs((out_txn.date_ - in_txn.date_).days)
    if delta == 0:
        score += 30
    elif delta <= 2:
        score += 20
    elif delta <= WINDOW_DAYS:
        score += 10
    blob = f"{out_txn.name or ''} {in_txn.name or ''}"
    if _PAYEE_RE.search(blob):
        score += 15
    # An inflow landing on a credit-card account is a card payment.
    is_credit_card_payment = in_on_card
    if is_credit_card_payment:
        score += 15
    return score, is_credit_card_payment


async def detect_transfers(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    today: date | None = None,
    lookback_days: int | None = None,
) -> TransferDetectionResult:
    """Pair internal transfers among the owner's recent, unpaired transactions.

    Idempotent: transactions already tied to a transfer (any status) are
    excluded, so re-running after each sync/import doesn't duplicate work or
    re-suggest a rejected pairing.

    Only transactions dated within ``lookback_days`` of ``today`` are
    considered (``settings.FINANCE_RULES_LOOKBACK_DAYS`` when not given;
    0 disables the window). A deep historical import accumulates coincidental
    amount matches by the hundreds, and every one of them lands in Review.
    """
    from app.core.config import settings

    today = today or date.today()
    if lookback_days is None:
        lookback_days = settings.FINANCE_RULES_LOOKBACK_DAYS
    result = TransferDetectionResult()

    acct_filters = [
        FinanceAccount.deleted_at.is_(None),
        _owner_clause(FinanceAccount.owner_user_id, owner_user_id),
    ]
    accounts = (await db.exec(select(FinanceAccount).where(*acct_filters))).all()
    account_type = {a.id: a.account_type for a in accounts}
    if not account_type:
        return result

    # Legs already claimed by a transfer (any status) — excluded so pairings
    # (including rejected ones) never recur.
    transfer_owner = _owner_clause(FinanceTransfer.owner_user_id, owner_user_id)
    paired_ids: set[int] = set()
    for col in (
        FinanceTransfer.from_transaction_id,
        FinanceTransfer.to_transaction_id,
    ):
        query = select(col).where(col.is_not(None), transfer_owner)
        rows = (await db.exec(query)).all()
        paired_ids.update(int(r) for r in rows)

    txn_filters = [
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.dedup_status != "duplicate",
        FinanceTransaction.is_transfer.is_(False),
        FinanceTransaction.transfer_group_id.is_(None),
        FinanceTransaction.account_id.in_(list(account_type.keys())),
        _owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
    ]
    if lookback_days:
        txn_filters.append(
            FinanceTransaction.date_ >= today - timedelta(days=lookback_days)
        )
    txns = (await db.exec(select(FinanceTransaction).where(*txn_filters))).all()
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
            if score >= SUGGEST_THRESHOLD:
                scored.append((score, is_ccp, out_txn, in_txn))

    scored.sort(key=lambda entry: entry[0], reverse=True)

    used: set[int] = set()
    for score, is_ccp, out_txn, in_txn in scored:
        if out_txn.id in used or in_txn.id in used:
            continue
        auto = score >= AUTO_THRESHOLD
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
                    status="confirmed" if auto else "suggested",
                )
                db.add(transfer)
                await db.flush()
                if auto:
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
        if auto:
            result.auto_paired += 1
        else:
            result.suggested += 1
    return result


def _flag_legs(
    out_txn: FinanceTransaction, in_txn: FinanceTransaction, transfer_id: int
) -> None:
    """Mark both legs of a confirmed transfer out of reports and cross-link."""
    for leg in (out_txn, in_txn):
        leg.is_transfer = True
        leg.excluded_from_reports = True
        leg.transfer_group_id = transfer_id
    out_txn.transfer_pair_transaction_id = in_txn.id
    in_txn.transfer_pair_transaction_id = out_txn.id
