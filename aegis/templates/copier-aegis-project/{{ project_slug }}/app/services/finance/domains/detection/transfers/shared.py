"""Thresholds, the candidate band, and the two-leg write."""

from __future__ import annotations

import re

from pydantic import BaseModel

from app.services.finance.models import (
    FinanceTransaction,
)


class TransferDetectionResult(BaseModel):
    """Counts from one detection pass."""

    auto_paired: int = 0
    # Flagged by their category's classification, not by finding a pair.
    category_flagged: int = 0
    # Same-account offsetting adjustment pairs (issuer bookkeeping),
    # excluded from reports without ever becoming transfers.
    adjustment_flagged: int = 0
    # Historical card/loan payments paired outside the lookback window.
    payment_paired: int = 0


WINDOW_DAYS = 5


AMOUNT_EXACT_TOLERANCE_CENTS = 200  # $2 fee tolerance -> full amount score


AMOUNT_BAND_PCT = 0.05  # within 5% (or $2) is a candidate at all


AUTO_THRESHOLD = 80


_CREDIT_CARD_TYPE = "credit_card"


_PAYEE_RE = re.compile(r"PAYMENT|PYMT|TRANSFER|XFER|EPAY|AUTOPAY|ACH", re.IGNORECASE)


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
