"""Refunds and corrections: a charge and its reversal."""

from __future__ import annotations

from datetime import date

from sqlmodel import or_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection import queries
from app.services.finance.models import (
    FinanceTransaction,
)
from app.services.shared.queries import owner_clause

_ADJUSTMENT_TOKENS = frozenset(
    {"ADJ", "ADJUSTMENT", "REDIST", "REVERSAL", "CORRECTION"}
)


def _looks_like_adjustment(txn: FinanceTransaction) -> bool:
    """Does either descriptor carry an adjustment token?

    Whole tokens, not substrings - "ADJACENT CAFE" must not match ADJ.
    """
    for text in (txn.name, txn.original_description):
        if not text:
            continue
        tokens = {
            t for t in "".join(c if c.isalnum() else " " for c in text.upper()).split()
        }
        if tokens & _ADJUSTMENT_TOKENS:
            return True
    return False


async def _flag_adjustment_pairs(db: AsyncSession, *, owner_user_id: int | None) -> int:
    """Neutralize same-account offsetting adjustment pairs.

    An issuer reshuffling balance between its own buckets books a
    same-day, equal-and-opposite pair on ONE account ("DR ADJ REDIST
    CADV PRIN" out, "Adj Redist Bal" back). Measured live: nine such
    pairs, every one inflating spend and income by its amount, one
    wearing a critical large-charge finding.

    The rule stays strict on purpose - same account, same date, equal
    and opposite, and at least one leg carrying an adjustment token.
    Anything looser starts eating real purchase-and-refund pairs.

    ``excluded_from_reports`` only, never ``is_transfer``: no money moved
    between accounts, and the Transfers review queue must not fill with
    issuer bookkeeping. Idempotent because flagged rows fall out of the
    candidate set. NO lookback, same reasoning as the category phase: an
    offsetting pair is not a coincidence at any age, and a 2024 pair
    inflates every historical figure until it is neutralized.
    """
    base_filters = [
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.dedup_status != "duplicate",
        FinanceTransaction.excluded_from_reports.is_(False),
        FinanceTransaction.is_transfer.is_(False),
        FinanceTransaction.amount != 0,
        owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
    ]

    # Two-step fetch so the whole ledger is never loaded: a coarse SQL
    # prefilter finds token-ish anchors (the Python token check is the
    # real gate - ILIKE '%ADJ%' happily matches "ADJACENT CAFE"), then
    # one query pulls everything on the anchors' account-days, because
    # the PARTNER leg ("Adj Redist Bal"'s debit twin) may carry no token.
    token_clause = or_(
        *(
            col.ilike(f"%{token}%")
            for token in _ADJUSTMENT_TOKENS
            for col in (
                FinanceTransaction.name,
                FinanceTransaction.original_description,
            )
        )
    )
    anchors = await queries.transaction_rows_where(db, [*base_filters, token_clause])
    anchor_keys = {
        (t.account_id, t.date_) for t in anchors if _looks_like_adjustment(t)
    }
    if not anchor_keys:
        return 0

    candidates = await queries.transaction_rows_where(
        db,
        [
            *base_filters,
            FinanceTransaction.account_id.in_({a for a, _ in anchor_keys}),
            FinanceTransaction.date_.in_({d for _, d in anchor_keys}),
        ],
        order_by_id=True,
    )

    groups: dict[tuple[int, date, int], list[FinanceTransaction]] = {}
    for txn in candidates:
        if (txn.account_id, txn.date_) not in anchor_keys:
            continue
        groups.setdefault((txn.account_id, txn.date_, abs(txn.amount)), []).append(txn)

    flagged = 0
    for members in groups.values():
        debits = [t for t in members if t.amount < 0]
        credits = [t for t in members if t.amount > 0]
        for debit, credit in zip(debits, credits, strict=False):
            if not (_looks_like_adjustment(debit) or _looks_like_adjustment(credit)):
                continue
            debit.excluded_from_reports = True
            credit.excluded_from_reports = True
            db.add(debit)
            db.add(credit)
            flagged += 2
    if flagged:
        await db.flush()
    return flagged
