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

from datetime import date

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.utils import current_date

from .adjustments import _flag_adjustment_pairs
from .categories import _flag_category_transfers
from .pairing import _pair_transfers
from .payment_history import _pair_payment_history
from .shared import TransferDetectionResult


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

    today = today or current_date()
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
