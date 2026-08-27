"""Uncovered spending: outflows no bill and no budget limit accounts for.

The sixth term of the month equation. Without it, unplanned spending is
invisible and every future month reads optimistic by exactly that amount
(confirmed live: ~40% of real spending sat in no bucket).

The subtlety this module exists for is that not all of it is a RATE.
Averaging a window that contains a one-off car repair asserts the repair
recurs, and the figure stays inflated for as long as the window holds it.
So a rate must be earned twice: the category's own history has to show
a habit (active in at least half the months since first seen), and even
then each window month is capped at a multiple of the median month -
the capped portion averages into the rate, the excess reports at face
value.
"""

from datetime import date
from typing import Any, NamedTuple

from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import add_months
from app.services.finance.domains.planning.budgets import queries
from app.services.finance.domains.planning.budgets.lines import get_or_create_budget
from app.services.finance.models import FinanceAccount, FinanceTransaction
from app.services.finance.utils import current_period_month

UNCOVERED_WINDOW_MONTHS = 3

SPIKE_CAP_MULTIPLIER = 3

RATE_EVIDENCE_LOOKBACK_MONTHS = 12


class UncoveredSpend(NamedTuple):
    """Uncovered spending, split by whether it looks like a rate.

    ``rate`` is cents per month; ``one_off`` is a total, not a rate, and
    the two are deliberately different units - averaging a one-off is
    exactly the mistake this split exists to stop.
    """

    rate: int
    one_off: int
    rate_by_category: dict[int | None, int]
    one_off_by_category: dict[int | None, int]
    counts: dict[int | None, int]


async def uncovered_spend(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    today: date | None = None,
    account_ids: list[int] | None = None,
) -> UncoveredSpend:
    """Observed spending no bill and no budget limit covers, split into a
    monthly rate and one-offs.

    Dividing the whole window by three asserts that all of it recurs, so
    a single car repair read as a monthly habit for three months running
    (reported live: a $1,734 repair became $578/mo of phantom cost).

    A rate needs a HABIT, and the window alone cannot see one: dental
    work that clusters into the window's three months looks exactly like
    groceries. So the judgment is split. History decides whether a habit
    exists at all: the category must be active in at least half the
    months of its own record - first-ever purchase to now, clamped to
    ``RATE_EVIDENCE_LOOKBACK_MONTHS`` - or every cent reports at face
    value. The window then sizes the rate for categories that qualify,
    with each month capped at ``SPIKE_CAP_MULTIPLIER`` times the median
    month and the excess split off as one-off. A category active in
    only one window month has a median of zero, so the whole amount is
    a one-off either way.
    """
    filters, (_lookback_start, window_end) = await uncovered_spend_filters(
        db,
        owner_user_id=owner_user_id,
        today=today,
        account_ids=account_ids,
        lookback_months=RATE_EVIDENCE_LOOKBACK_MONTHS,
    )
    rows = await queries.category_dated_amounts_where(db, filters)

    window_start = add_months(window_end, -UNCOVERED_WINDOW_MONTHS)
    window_months = [
        (month.year, month.month)
        for month in (
            add_months(window_start, offset)
            for offset in range(UNCOVERED_WINDOW_MONTHS)
        )
    ]
    monthly: dict[int | None, dict[tuple[int, int], int]] = {}
    counts: dict[int | None, int] = {}
    active_months: dict[int | None, set[tuple[int, int]]] = {}
    lookback_first: dict[int | None, date] = {}
    for category_id, when, amount in rows:
        active_months.setdefault(category_id, set()).add((when.year, when.month))
        if category_id not in lookback_first or when < lookback_first[category_id]:
            lookback_first[category_id] = when
        if when < window_start:
            continue
        by_month = monthly.setdefault(category_id, dict.fromkeys(window_months, 0))
        by_month[(when.year, when.month)] -= amount
        counts[category_id] = counts.get(category_id, 0) + 1

    # The span is the category's RECORD, not its recent filtered
    # activity: toys bought since 2020 with one quiet year must not
    # read as a brand-new category. Uncategorized rows have no record
    # to look up and fall back to their first filtered appearance.
    first_spend = await queries.category_first_spend(db, set(monthly))

    rate_by_category: dict[int | None, int] = {}
    one_off_by_category: dict[int | None, int] = {}
    for category_id, by_month in monthly.items():
        seen = (
            first_spend.get(category_id, lookback_first[category_id])
            if category_id is not None
            else lookback_first[category_id]
        )
        span = min(
            (window_end.year - seen.year) * 12 + window_end.month - seen.month,
            RATE_EVIDENCE_LOOKBACK_MONTHS,
        )
        if 2 * len(active_months[category_id]) < span:
            # Quiet for most of its own record: whatever the window
            # shape, this is episodic. Only the window's spending is
            # the card's population - older months are evidence, not
            # bills.
            one_off_by_category[category_id] = sum(by_month.values())
            continue
        cap = SPIKE_CAP_MULTIPLIER * sorted(by_month.values())[len(by_month) // 2]
        capped = sum(min(total, cap) for total in by_month.values())
        if rate := round(capped / UNCOVERED_WINDOW_MONTHS):
            rate_by_category[category_id] = rate
        if excess := sum(by_month.values()) - capped:
            one_off_by_category[category_id] = excess
    return UncoveredSpend(
        rate=sum(rate_by_category.values()),
        one_off=sum(one_off_by_category.values()),
        rate_by_category=rate_by_category,
        one_off_by_category=one_off_by_category,
        counts=counts,
    )


async def uncovered_spending_rate(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    today: date | None = None,
    account_ids: list[int] | None = None,
) -> int:
    """Cents/month of uncovered spending that actually looks like a rate.

    The sixth term of the month equation: without it, unplanned spending
    is invisible and every future month reads optimistic by exactly that
    amount (confirmed live: ~40% of real spending was in no bucket).
    """
    return (
        await uncovered_spend(
            db, owner_user_id=owner_user_id, today=today, account_ids=account_ids
        )
    ).rate


async def uncovered_spend_filters(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    today: date | None,
    account_ids: list[int] | None,
    lookback_months: int = UNCOVERED_WINDOW_MONTHS,
) -> tuple[list[Any], tuple[date, date]]:
    """The uncovered-spend population, shared by the rate and its
    per-category breakdown so the popup's rows always sum to the
    cell's figure. Returns (filters, (window_start, window_end)) -
    ``lookback_months`` widens the date floor for the habit-evidence
    read without changing what counts as uncovered."""
    today = today or date.today()
    window_end = date(today.year, today.month, 1)
    window_start = add_months(window_end, -lookback_months)

    budget = await get_or_create_budget(
        db, owner_user_id=owner_user_id, period_month=current_period_month()
    )
    budgeted_category_ids = {
        line.category_id
        for line in await queries.budget_lines_for_period(
            db, budget.id, current_period_month()
        )
        if line.category_id is not None
    }

    live_accounts = select(FinanceAccount.id).where(FinanceAccount.deleted_at.is_(None))
    filters: list[Any] = [
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.dedup_status != "duplicate",
        FinanceTransaction.excluded_from_reports.is_(False),
        FinanceTransaction.is_transfer.is_(False),
        FinanceTransaction.account_id.in_(live_accounts),
        FinanceTransaction.amount < 0,
        FinanceTransaction.date_ >= window_start,
        FinanceTransaction.date_ < window_end,
        FinanceTransaction.recurring_stream_id.is_(None),
        # A reconciliation adjustment is bookkeeping, not spending.
        or_(
            FinanceTransaction.external_id_source.is_(None),
            FinanceTransaction.external_id_source != "reconcile",
        ),
    ]
    if owner_user_id is not None:
        filters.append(FinanceTransaction.owner_user_id == owner_user_id)
    if account_ids is not None:
        filters.append(FinanceTransaction.account_id.in_(account_ids))
    if budgeted_category_ids:
        filters.append(
            or_(
                FinanceTransaction.category_id.is_(None),
                FinanceTransaction.category_id.notin_(budgeted_category_ids),
            )
        )
    return filters, (window_start, window_end)
