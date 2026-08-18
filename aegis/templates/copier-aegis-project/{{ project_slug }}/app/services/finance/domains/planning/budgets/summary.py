"""Reading a period back: where the money went, and whether it adds up.

The month equation lives here - income minus bills minus budgets minus
goals minus envelopes minus uncovered spending - along with the per-cell
backup the popups show and the deterministic cuts that close a negative
month. ``outlook`` runs this same equation forward over future months.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Literal

from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import CADENCES, add_months
from app.services.finance.domains.detection.insights.commitments import (
    MONTHLY_FACTOR,
    commitment_rollup,
    is_commitment,
    is_paused,
)
from app.services.finance.domains.ledger import categories
from app.services.finance.domains.planning import envelopes, goals, recurring
from app.services.finance.domains.planning.budgets import queries
from app.services.finance.domains.planning.budgets.lines import (
    budget_line_status,
    get_or_create_budget,
)
from app.services.finance.models import (
    FinanceAccount,
    FinanceBudgetCategory,
    FinanceRecurringStream,
    FinanceTransaction,
)
from app.services.finance.schemas import (
    BudgetBucketResponse,
    BudgetLineResponse,
    BudgetStatDetailsResponse,
    BudgetStatsResponse,
    BudgetSummaryResponse,
    BudgetTrimPlan,
    BudgetTrimResponse,
    GoalAsk,
    StatDetailRow,
)
from app.services.finance.utils import (
    current_period_month,
    monthly_income,
    transaction_payee_key,
)


def plan_budget_trims(
    lines: list[BudgetLineResponse],
    *,
    deficit: int,
    goals: list[GoalAsk] | None = None,
) -> BudgetTrimPlan:
    """Deterministic cuts that close a negative month.

    The rules, stated once so the UI and any later decision layer share
    them. TIER 1: pause a goal before cutting a budget - a dream
    deferred beats groceries squeezed. Goals pause largest-need-first
    (fewest dreams disturbed), each recovering its whole monthly need
    (a pause is all-or-nothing), until the gap is covered or goals run
    out. TIER 2: a line's FLOOR is what it has already spent this period
    (a budget below money already gone is a lie, not a plan); cuts
    distribute proportionally to each line's slack above its floor,
    largest-remainder rounded so they sum exactly. Whatever neither tier
    covers is returned as ``residual`` - the part of the gap that
    belongs to bills or income. Every row carries ``kind``
    (``pause_goal`` | ``cut_budget``).
    """
    if deficit <= 0:
        return BudgetTrimPlan()
    pauses: list[BudgetTrimResponse] = []
    for goal in sorted(
        goals or [],
        key=lambda g: (-g.monthly_need, g.label.casefold()),
    ):
        if deficit <= 0:
            break
        need = goal.monthly_need
        if need <= 0:
            continue
        pauses.append(
            BudgetTrimResponse(
                kind="pause_goal",
                account_id=goal.account_id,
                label=goal.label or "Goal",
                recovered=need,
            )
        )
        deficit -= need
    if deficit <= 0:
        return BudgetTrimPlan(cuts=pauses)
    slack = [
        (line, max(0, line.allocated_amount - max(line.spent_amount, 0)))
        for line in lines
    ]
    slack = [(line, room) for line, room in slack if room > 0]
    total_slack = sum(room for _line, room in slack)
    if total_slack == 0:
        return BudgetTrimPlan(cuts=pauses, residual=deficit)
    take = min(deficit, total_slack)
    raw = [(line, room, take * room / total_slack) for line, room in slack]
    cuts = [(line, room, int(share)) for line, room, share in raw]
    remainder = take - sum(cut for _l, _r, cut in cuts)
    # Largest fractional parts absorb the leftover cents, never past slack.
    by_fraction = sorted(
        range(len(cuts)), key=lambda i: raw[i][2] - cuts[i][2], reverse=True
    )
    for i in by_fraction:
        if remainder <= 0:
            break
        line, room, cut = cuts[i]
        if cut < room:
            cuts[i] = (line, room, cut + 1)
            remainder -= 1
    return BudgetTrimPlan(
        cuts=pauses
        + [
            BudgetTrimResponse(
                kind="cut_budget",
                id=line.id,
                label=line.category_name or line.payee_label or "Overall",
                category_id=line.category_id,
                payee_key=line.payee_key,
                allocated_amount=line.allocated_amount,
                spent_amount=line.spent_amount,
                cut=cut,
                suggested_amount=line.allocated_amount - cut,
            )
            for line, _room, cut in cuts
            if cut > 0
        ],
        residual=deficit - take,
    )


def _prior_period_month(period_month: int) -> int:
    start, _ = queries.month_bounds(period_month)
    prior_start = add_months(start, -1)
    return prior_start.year * 100 + prior_start.month


def _commitment_variance_status(
    actual: int, prior: int | None
) -> tuple[Literal["good", "warn"], int | None]:
    """A Fixed/Non-monthly line reads variance against what it cost LAST
    period, not against a limit - it isn't one. Never "critical": a bill
    can't be over budget on itself, only worth a second look if it moved.
    Nothing to compare yet (no prior-period charge, or this period hasn't
    posted) reads as "good"/on schedule rather than a false swing."""
    if not actual or prior is None:
        return "good", None
    variance = actual - prior
    tolerance = max(200, round(prior * 0.02))  # $2 floor or 2%, whichever's bigger
    return ("warn" if abs(variance) > tolerance else "good"), variance


async def budget_summary(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    period_month: int | None = None,
    account_ids: list[int] | None = None,
) -> BudgetSummaryResponse:
    """Flexible: explicit limits the owner chose to track (category or
    payee) - the only bucket with a real spend-vs-allocation status.
    Fixed/Non-monthly: recurring commitments shown for CONTEXT only
    (an earlier version gave every detected bill, including the
    mortgage, its own spend-vs-allocation status - wrong, a bill's own
    cost isn't a limit anyone set). These read a variance-vs-last-month
    signal instead and never go "critical".

    Query count does NOT grow with the number of budget lines or
    recurring streams: one fetch of this period's transactions and one
    of last period's (each tallied by category/payee-key/recurring-
    stream in a single Python pass) stand in for what would otherwise
    be a spend lookup per line. Do not "simplify" steps 4/5 below into
    per-line queries - that is exactly the N+1 this was built to avoid.
    """
    month = period_month or current_period_month()
    start, end = queries.month_bounds(month)
    prior_start, prior_end = queries.month_bounds(_prior_period_month(month))

    # 1-2. The budget + its explicit lines for this period.
    budget = await get_or_create_budget(
        db, owner_user_id=owner_user_id, period_month=month
    )
    lines = await queries.budget_lines_for_period(db, budget.id, month)

    # 3. Category display names, batched.
    names = await categories.category_names(
        db, {line.category_id for line in lines if line.category_id is not None}
    )

    # 4. ONE fetch of THIS period's outflows, tallied by category,
    # payee-key, AND recurring-stream in a single Python pass - this
    # is the line that keeps the whole method O(1) queries regardless
    # of how many budget lines or streams exist.
    txn_rows = await queries.outflow_tuples(
        db,
        owner_user_id=owner_user_id,
        start=start,
        end=end,
        account_ids=account_ids,
    )
    spent_by_category: dict[int, int] = defaultdict(int)
    spent_by_payee: dict[str, int] = defaultdict(int)
    spent_by_stream: dict[int, int] = defaultdict(int)
    for (
        cat_id,
        merchant_name,
        original_description,
        name,
        amount,
        stream_id,
    ) in txn_rows:
        spend = -amount
        if cat_id is not None:
            spent_by_category[cat_id] += spend
        key = transaction_payee_key(merchant_name, original_description, name)
        if key:
            spent_by_payee[key] += spend
        if stream_id is not None:
            spent_by_stream[stream_id] += spend

    # 5. ONE fetch of LAST period's per-stream spend - the "vs last
    # month" variance signal on Fixed/Non-monthly, a second FIXED
    # query, not one per stream.
    prior_rows = await queries.outflow_tuples(
        db,
        owner_user_id=owner_user_id,
        start=prior_start,
        end=prior_end,
        account_ids=account_ids,
    )
    spent_by_stream_prior: dict[int, int] = defaultdict(int)
    for *_ignored, amount, stream_id in prior_rows:
        if stream_id is not None:
            spent_by_stream_prior[stream_id] += -amount

    # 6. Recurring commitments (existing detection, ~3 fixed queries),
    # reused rather than re-derived - same source /recurring reads.
    streams = await recurring.list_recurring(db, owner_user_id=owner_user_id)
    transfer_ids = await recurring.transfer_stream_ids(db, [s.id for s in streams])
    streams = [s for s in streams if s.id not in transfer_ids]
    if account_ids is not None:
        streams = [s for s in streams if s.account_id in account_ids]
    rollup = commitment_rollup(streams)
    stream_category_names = await recurring.stream_category_names(
        db, {s.id for s in rollup["fixed"] + rollup["non_monthly"]}
    )

    def commitment_line(stream: FinanceRecurringStream) -> BudgetLineResponse:
        typical = int(stream.average_amount or 0)
        actual = spent_by_stream.get(stream.id, 0)
        status, variance = _commitment_variance_status(
            actual, spent_by_stream_prior.get(stream.id)
        )
        return BudgetLineResponse(
            id=stream.id,
            category_id=stream.category_id,
            category_name=stream_category_names.get(stream.id),
            payee_key=None,
            payee_label=None,
            allocated_amount=typical,
            spent_amount=actual,
            status=status,
            variance_amount=variance,
        )

    def user_line(line: FinanceBudgetCategory) -> BudgetLineResponse:
        spent = (
            spent_by_category.get(line.category_id, 0)
            if line.category_id is not None
            else spent_by_payee.get(line.payee_key or "", 0)
        )
        return BudgetLineResponse(
            id=line.id,
            category_id=line.category_id,
            category_name=names.get(line.category_id)
            if line.category_id is not None
            else None,
            payee_key=line.payee_key,
            payee_label=line.payee_label,
            allocated_amount=line.allocated_amount,
            spent_amount=spent,
            status=budget_line_status(line.allocated_amount, spent),
            variance_amount=None,
        )

    def bucket(
        name: Literal["fixed", "non_monthly", "flexible"],
        item_lines: list[BudgetLineResponse],
    ) -> BudgetBucketResponse:
        return BudgetBucketResponse(
            name=name,
            total_allocated=sum(row.allocated_amount for row in item_lines),
            total_spent=sum(row.spent_amount for row in item_lines),
            lines=item_lines,
        )

    fixed_lines = [commitment_line(s) for s in rollup["fixed"]]
    non_monthly_lines = [commitment_line(s) for s in rollup["non_monthly"]]
    flexible_lines = [user_line(line) for line in lines]

    # 7. Stats strip - derived entirely from data already in memory
    # above, no further queries.
    over_budget = [row for row in flexible_lines if row.status == "critical"]
    today = date.today()
    days_left = (end - today).days if start <= today < end else 0
    flexible_spent = sum(row.spent_amount for row in flexible_lines)
    flexible_allocated = sum(row.allocated_amount for row in flexible_lines)
    # MONTHLY-EQUIVALENT, not the sum of face values: this is the
    # header's "Bills / month" figure AND the number ``month_net``
    # subtracts below, so the two must ride the same footing. A
    # quarterly $300 bill costs $100 a month; summing the face
    # values instead (the original) overstated the cell by the
    # whole non-monthly book, and the strip visibly failed its own
    # arithmetic - the three cells on display did not subtract to
    # the fourth.
    fixed_total = rollup["monthly_total"]

    # 8. The month's bottom line: confirmed income minus confirmed
    # bills minus budget allocations, all monthly-equivalent - the
    # same commitment gate and factors the forecast walks with, so
    # this verdict and the Projected tab cannot disagree. Budget
    # lines are the flexible ones only; a category a bill covers is
    # already excluded from budgets by the suggestion guards.

    income_total, income_count = monthly_income(streams)
    # Goals ask their monthly need of the month, the same
    # commitment-gate discipline bills ride:
    # paused/reached goals ask nothing, by the pure-math contract.
    goal_accounts = await goals.list_goals(db, owner_user_id=owner_user_id)
    figures = goals.MonthlyFigures(
        income_total=income_total,
        committed=fixed_total + flexible_allocated,
    )
    engine_rows = [
        (str(account.id), meta, account.current_balance or 0)
        for account in goal_accounts
        if (meta := goals.goal_metadata(account.metadata_)) is not None
    ]
    asks = goals.allocate_month(figures, engine_rows, today=today)
    goal_asks = [
        GoalAsk(
            account_id=account.id,
            label=account.name,
            monthly_need=asks.get(str(account.id), 0),
        )
        for account in goal_accounts
        if goals.goal_metadata(account.metadata_) is not None
    ]
    goals_total = sum(g.monthly_need for g in goal_asks)

    # Auto-credit envelopes are spoken-for money too: the allowance
    # leaves the spendable month whether or not anyone clicks. Manual
    # envelopes ask nothing - crediting them is a choice made live.
    envelope_credits = [
        int(meta.monthly_credit * CADENCES[meta.cadence].monthly_factor)
        for account in await envelopes.list_envelopes(db, owner_user_id=owner_user_id)
        if (meta := envelopes.envelope_metadata(account.metadata_)) is not None
        and meta.auto_credit
        and meta.monthly_credit
    ]
    envelopes_total = sum(envelope_credits)

    # The sixth term: observed spending no bill and no limit covers.
    everything_else = await uncovered_spending_rate(
        db, owner_user_id=owner_user_id, today=today, account_ids=account_ids
    )

    # Subtracts the figures the header STRIP shows, not equivalents of
    # them recomputed here - the cells and this verdict are one
    # arithmetic statement, and a reader checking it by hand has to
    # get the same answer.
    month_net = (
        income_total
        - fixed_total
        - flexible_allocated
        - goals_total
        - envelopes_total
        - everything_else
    )

    # 9. When the month lands negative, the summary carries its own
    # fix: pause-a-goal rows first, then deterministic per-line cuts
    # (see plan_budget_trims). One payload, so the tab offers the
    # adjustment beside the verdict and a later decision layer reads
    # the same structure.
    plan = plan_budget_trims(
        flexible_lines,
        deficit=max(0, -month_net),
        goals=goal_asks,
    )

    stats = BudgetStatsResponse(
        flexible_spent=flexible_spent,
        flexible_allocated=flexible_allocated,
        days_left_in_period=max(days_left, 0),
        flexible_count=len(flexible_lines),
        on_track_count=len(flexible_lines) - len(over_budget),
        over_budget_count=len(over_budget),
        over_budget_labels=[
            row.category_name or row.payee_label or "Overall" for row in over_budget
        ],
        fixed_total=fixed_total,
        fixed_count=len(fixed_lines) + len(non_monthly_lines),
        income_total=income_total,
        income_count=income_count,
        goals_total=goals_total,
        goals_count=sum(1 for g in goal_asks if g.monthly_need > 0),
        envelopes_total=envelopes_total,
        envelopes_count=len(envelope_credits),
        everything_else=everything_else,
        month_net=month_net,
        trim_residual=plan.residual,
    )

    return BudgetSummaryResponse(
        period_month=month,
        buckets=[
            bucket("fixed", fixed_lines),
            bucket("non_monthly", non_monthly_lines),
            bucket("flexible", flexible_lines),
        ],
        stats=stats,
        trims=plan.cuts,
    )


async def uncovered_spending_rate(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    today: date | None = None,
    account_ids: list[int] | None = None,
) -> int:
    """Cents/month of observed spending no bill and no budget limit
    covers - the trailing 3 full months' average of spend-space
    outflows that are neither linked to a recurring stream nor in a
    budgeted category. The sixth term of the month equation: without
    it, unplanned spending is invisible and every future month reads
    optimistic by exactly that amount (confirmed live: ~40% of real
    spending was in no bucket).
    """
    filters, _window = await uncovered_spend_filters(
        db, owner_user_id=owner_user_id, today=today, account_ids=account_ids
    )
    total = await queries.sum_amount_where(db, filters)
    return round(-total / 3)


async def uncovered_spend_filters(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    today: date | None,
    account_ids: list[int] | None,
) -> tuple[list[Any], tuple[date, date]]:
    """The uncovered-spend population, shared by the rate and its
    per-category breakdown so the popup's rows always sum to the
    cell's figure. Returns (filters, (window_start, window_end))."""
    today = today or date.today()
    window_end = date(today.year, today.month, 1)
    window_start = add_months(window_end, -3)

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


async def budget_stat_details(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    today: date | None = None,
    account_ids: list[int] | None = None,
) -> BudgetStatDetailsResponse:
    """Per-row backup for the header cells, for the click-a-cell popup.

    Income and Bills mirror the cells' own math row for row (same
    commitment gate, same monthly-equivalent factors as
    ``monthly_income``/``commitment_rollup``), so the rows always sum
    to the cell. Everything-else is the uncovered-spend bucket grouped
    by category, over the SAME filters as the rate.
    """
    today = today or date.today()
    streams = await recurring.list_recurring(db, owner_user_id=owner_user_id)

    income_rows = [
        StatDetailRow(
            label=s.name,
            value=int(
                (s.expected_amount or s.average_amount or 0)
                * MONTHLY_FACTOR.get(s.frequency, 0.0)
            ),
            frequency=None
            if MONTHLY_FACTOR.get(s.frequency, 0.0) >= 1.0
            else s.frequency,
        )
        for s in streams
        if s.direction == "inflow"
        and not s.is_muted
        and not is_paused(s, today)
        and is_commitment(s)
        and MONTHLY_FACTOR.get(s.frequency, 0.0) > 0
    ]
    income_rows.sort(key=lambda r: -r.value)

    rollup = commitment_rollup(streams, today=today)
    bills_rows = [
        StatDetailRow(
            label=s.name,
            value=int((s.average_amount or 0) * MONTHLY_FACTOR.get(s.frequency, 0.0)),
            frequency=None
            if MONTHLY_FACTOR.get(s.frequency, 0.0) >= 1.0
            else s.frequency,
            per_period_amount=None
            if MONTHLY_FACTOR.get(s.frequency, 0.0) >= 1.0
            else int(s.average_amount or 0),
        )
        for s in rollup["fixed"] + rollup["non_monthly"]
    ]
    bills_rows.sort(key=lambda r: -r.value)

    filters, (window_start, window_end) = await uncovered_spend_filters(
        db, owner_user_id=owner_user_id, today=today, account_ids=account_ids
    )
    grouped = await queries.grouped_category_totals_where(db, filters)
    names = await categories.category_names(
        db, {category_id for category_id, _n, _total in grouped if category_id}
    )
    else_rows = [
        StatDetailRow(
            label=names.get(category_id) or "Uncategorized",
            value=round(-int(total) / 3),
            transaction_count=int(count or 0),
        )
        for category_id, count, total in grouped
    ]
    else_rows.sort(key=lambda r: -r.value)

    return BudgetStatDetailsResponse(
        income=income_rows,
        bills=bills_rows,
        everything_else=else_rows,
        window_start=window_start,
        window_end=window_end,
    )
