"""Internal-transfer detection + pairing (FIN-26).

Kills the #1 aggregator bug: money moved between a user's own accounts (a
credit-card payment, a checking->savings sweep) counted as spending on the
outflow side while never netting out. This pairs the two legs and flags them
out of spend/income reports.

Run after each sync/import batch. Only high-confidence matches
(>= ``AUTO_THRESHOLD``) pair, and pairing hides both legs from reports.
We NEVER hide money below that bar: a Venmo to a friend looks like a
transfer but is real spending, so a fuzzy near-miss simply stays visible
as ordinary spend/income. A transaction is a leg of at most one transfer
(DB partial-uniques on both legs); an existing transfer row keeps that
pairing from recurring.

Scoring note: the candidate band is ``max($2, 5%)`` with the full amount
score reserved for an exact ("within $2") match - exact same-day moves
pair, fuzzy ones never silently vanish.
"""

from __future__ import annotations

from datetime import date, timedelta
import re

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import or_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.services.finance.domains.detection import queries
from app.services.finance.models import (
    FinanceAccount,
    FinanceTransaction,
    FinanceTransfer,
)

WINDOW_DAYS = 5
AMOUNT_EXACT_TOLERANCE_CENTS = 200  # $2 fee tolerance -> full amount score
AMOUNT_BAND_PCT = 0.05  # within 5% (or $2) is a candidate at all
AUTO_THRESHOLD = 80
_CREDIT_CARD_TYPE = "credit_card"
_PAYEE_RE = re.compile(r"PAYMENT|PYMT|TRANSFER|XFER|EPAY|AUTOPAY|ACH", re.IGNORECASE)


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
    considered for PAIRING (``settings.FINANCE_RULES_LOOKBACK_DAYS`` when not
    given; 0 disables the window). A deep historical import accumulates
    coincidental amount matches by the hundreds, and every one of them lands
    in Review. The category phase that follows pairing has no window - see
    ``_flag_category_transfers``.
    """
    from app.core.config import settings

    today = today or date.today()
    if lookback_days is None:
        lookback_days = settings.FINANCE_RULES_LOOKBACK_DAYS
    result = await _pair_transfers(
        db, owner_user_id=owner_user_id, today=today, lookback_days=lookback_days
    )
    # ALWAYS runs, including when pairing bails early (no accounts with
    # candidates on both sides): a lone "Transfer Out" with no counterpart
    # anywhere is precisely the case this phase exists for.
    result.category_flagged = await _flag_category_transfers(
        db, owner_user_id=owner_user_id
    )
    result.adjustment_flagged = await _flag_adjustment_pairs(
        db, owner_user_id=owner_user_id
    )
    result.payment_paired = await _pair_payment_history(db, owner_user_id=owner_user_id)
    return result


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
        _owner_clause(FinanceAccount.owner_user_id, owner_user_id),
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
        _owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
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
            _owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
        ],
    )
    for txn in rows:
        txn.is_transfer = True
        txn.excluded_from_reports = True
        db.add(txn)
    if rows:
        await db.flush()
    return len(rows)


# Ledger-adjustment vocabulary, matched as whole tokens of the descriptor.
# REFUND is deliberately absent: a same-day purchase-and-refund is real
# activity the reader should see, not bookkeeping to vanish.
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
        _owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
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
            _owner_clause(FinanceAccount.owner_user_id, owner_user_id),
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
            _owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
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
