"""What every rule needs: the thresholds, the result tally, the owner
scope, and the one writer that dedups.

The thresholds sit here rather than beside the rules that read them
because they do not partition cleanly - ``monthly_category_spend`` is
shared machinery and reads ``OVERSPEND_MIN_HISTORY``, so at least one
would have to be imported backwards. One block, as it was, tuned by
test rather than by a config surface.

Its own module because the rules import it and the dispatcher imports
the rules: anywhere else closes a cycle.
"""

from __future__ import annotations

from datetime import date
import re

from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection import queries
from app.services.finance.domains.detection.insights.formatting import (
    month_key,
    month_start_before,
)
from app.services.finance.models import (
    FinanceAccount,
    FinanceInsight,
    FinanceTransaction,
)
from app.services.shared.queries import owner_clause

PRICE_HIKE_THRESHOLD = 1.10  # >10% over the stream's average
OVERSPEND_MULTIPLE = 1.5  # > 1.5x the 3-month median
OVERSPEND_MIN_HISTORY = 3  # need >= 3 prior full months
# Comparing on pace shrinks the baseline, which is the point (the rule can
# now fire while the month can still be steered) but also makes the early
# days dangerous: three days of history is mostly noise, and one grocery
# run against it reads as an emergency. Judge nothing until a quarter of
# the month has passed, and never multiply a baseline too small to mean
# anything.
OVERSPEND_MIN_ELAPSED = 0.25
OVERSPEND_MIN_BASELINE = 5_000  # cents
_FEE_PFC = "BANK_FEES"
_FEE_RE = re.compile(r"FEE|INTEREST CHARGE|FINANCE CHARGE", re.IGNORECASE)

# large_transaction: an outlier is judged against its OWN account, because a
# normal charge on a grocery card and a normal charge on a mortgage account are
# nothing alike. The floors keep a quiet account from crying wolf over an
# ordinary purchase that happens to beat its small median.
LARGE_TXN_WINDOW_DAYS = 35  # how far back to look for candidates
LARGE_TXN_BASELINE_DAYS = 90  # the account's own recent norm
LARGE_TXN_MIN_BASELINE = 10  # peers needed before the median is trusted
LARGE_TXN_MULTIPLE = 4  # x the account's median outflow
LARGE_TXN_CRITICAL_MULTIPLE = 10  # x the median -> critical, not warning
LARGE_TXN_FLOOR = 20_000  # cents; never alert below this
LARGE_TXN_THIN_FLOOR = 50_000  # cents; the only test when history is thin

# Credit-card / liquidity rules. These are the "someone told the system to
# look" checks: a card in trouble is flagged by code reading the provider's
# own liability detail, never by a model happening to notice. APRs are basis
# points (2999 = 29.99%); amounts are cents.
HIGH_APR_BPS = 2_000  # >= 20.00% counts as expensive money
HIGH_APR_MIN_BALANCE = 10_000  # ignore trivial carried balances
UTILIZATION_WARNING = 0.80  # of the credit limit
UTILIZATION_CRITICAL = 0.95
MIN_PAYMENT_LOOKAHEAD_DAYS = 14  # how far ahead a due date is "soon"
RUNWAY_DAYS = 60  # projection window for the cash-runway rule
SUBSCRIPTION_CREEP_MULTIPLE = 1.25  # x the prior-months median


class InsightGenerationResult(BaseModel):
    """Counts from one generation pass."""

    created: int = 0


def live_account_ids(owner_user_id: int | None):
    """Subquery selecting the owner's non-deleted account ids."""
    return select(FinanceAccount.id).where(
        FinanceAccount.deleted_at.is_(None),
        owner_clause(FinanceAccount.owner_user_id, owner_user_id),
    )


async def monthly_category_spend(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    today: date,
    months_back: int = OVERSPEND_MIN_HISTORY,
    through_day: int | None = None,
) -> dict[int, dict[str, int]]:
    """``{category_id: {"YYYY-MM": spend_cents}}`` over the trailing window.

    Transfer-excluded, categorized outflows only. Shared by the overspend rule
    and the analyst's snapshot so that "more than usual" means exactly the same
    thing wherever the product says it.

    ``through_day`` counts only spend on or before that day of the month, in
    every month including the current one. Without it a part-finished month is
    weighed against whole prior months: on the 9th that is nine days against
    thirty, which makes almost every category look cheap and makes the
    overspend rule almost unable to fire until the month is over. Pass
    ``pace_day(today)``.
    """
    rows = await queries.transaction_rows_where(
        db,
        [
            owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
            FinanceTransaction.excluded_from_reports.is_(False),
            FinanceTransaction.amount < 0,
            FinanceTransaction.category_id.is_not(None),
            FinanceTransaction.date_ >= month_start_before(today, months_back),
            FinanceTransaction.account_id.in_(live_account_ids(owner_user_id)),
        ],
    )

    by_category: dict[int, dict[str, int]] = {}
    for txn in rows:
        if through_day is not None and txn.date_.day > through_day:
            continue
        months = by_category.setdefault(txn.category_id, {})
        key = month_key(txn.date_)
        months[key] = months.get(key, 0) + abs(txn.amount)
    return by_category


async def create_insight_if_new(
    db: AsyncSession,
    *,
    owner_user_id: int,
    insight_type: str,
    dedup_key: str,
    severity: str,
    title: str,
    body: str,
    detected_amount: int | None = None,
    related_stream_id: int | None = None,
    related_transaction_id: int | None = None,
    related_category_id: int | None = None,
    related_account_id: int | None = None,
) -> FinanceInsight | None:
    """Insert an insight unless its dedup_key already exists.

    Returns the new row, or None when one was already there. Truthy exactly
    when it created something, so rules that only count creations read the
    same as they always did.
    """
    if await queries.insight_exists(
        db, owner_user_id=owner_user_id, dedup_key=dedup_key
    ):
        return None
    insight = FinanceInsight(
        owner_user_id=owner_user_id,
        insight_type=insight_type,
        severity=severity,
        title=title,
        body=body,
        dedup_key=dedup_key,
        detected_amount=detected_amount,
        related_stream_id=related_stream_id,
        related_transaction_id=related_transaction_id,
        related_category_id=related_category_id,
        related_account_id=related_account_id,
    )
    db.add(insight)
    await db.flush()
    return insight
