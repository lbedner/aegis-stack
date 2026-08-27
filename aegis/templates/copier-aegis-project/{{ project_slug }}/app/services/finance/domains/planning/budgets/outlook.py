"""Months ahead, and reading a plan out of plain language.

The outlook runs the header's own equation forward - bills at face value
on their real cadence, so the month the annual premium lands looks like
that month rather than like an average. Goal parsing is the other
forward-looking verb: it turns "cut back on Starbucks" into the numbers a
budget line would need.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import re

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import (
    CADENCES,
    CASH_ACCOUNT_TYPES,
    ONE_TIME_FREQUENCY,
    add_months,
)
from app.services.finance.domains.detection.insights.commitments import (
    is_commitment,
    is_paused,
)
from app.services.finance.domains.ledger import accounts, categories
from app.services.finance.domains.planning import (
    allocation,
    envelopes,
    recurring,
)
from app.services.finance.domains.planning import queries as planning_queries
from app.services.finance.domains.planning.budgets import queries
from app.services.finance.domains.planning.budgets.lines import get_or_create_budget
from app.services.finance.domains.planning.budgets.uncovered import (
    uncovered_spending_rate,
)
from app.services.finance.models import FinanceTransaction
from app.services.finance.schemas import BudgetMonthOutlook, GoalParseResponse
from app.services.finance.utils import (
    FREQUENCY_STEPS,
    current_period_month,
    display_cash_balance,
    transaction_payee_key,
)


async def budget_month_outlook(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    months: int = 6,
    today: date | None = None,
    account_ids: list[int] | None = None,
) -> list[BudgetMonthOutlook]:
    """The header equation computed per month, months ahead - bills at
    FACE VALUE on their real cadence, so the month the annual premium
    lands looks like that month and not like an average. "Fine this
    month" and "broke in October" become visible from one page.

    Same population rules as the header: confirmed commitments only,
    muted/paused out, transfers (card payments included) out of the
    bills figure - swipes are already counted in budgets. Budgets,
    goals, and envelopes ask their standing monthly amounts of every
    month (they are plans, not occurrences).
    """
    today = today or date.today()
    first = date(today.year, today.month, 1)
    horizon_end = add_months(first, months)

    streams = await recurring.list_recurring(db, owner_user_id=owner_user_id)
    # Same scoping rule as budget_summary, the header this pages.
    if account_ids is not None:
        streams = [s for s in streams if s.account_id in account_ids]
    transfer_ids = await recurring.transfer_stream_ids(db, [s.id for s in streams])
    due_in: dict[tuple[int, int, str], int] = {}
    for stream in streams:
        if (
            stream.is_muted
            or is_paused(stream, today)
            or stream.id in transfer_ids
            or not is_commitment(stream)
            or stream.next_expected_date is None
        ):
            continue
        amount = stream.expected_amount or stream.average_amount or 0
        if amount <= 0:
            continue
        direction = "in" if stream.direction == "inflow" else "out"
        if stream.frequency == ONE_TIME_FREQUENCY:
            when = stream.next_expected_date
            if today <= when < horizon_end:
                key = (when.year, when.month, direction)
                due_in[key] = due_in.get(key, 0) + amount
            continue
        step = FREQUENCY_STEPS.get(stream.frequency)
        if step is None:
            continue
        when = stream.next_expected_date
        guard = 0
        while when < today and guard < 400:
            when = step(when)
            guard += 1
        while when < horizon_end and guard < 400:
            key = (when.year, when.month, direction)
            due_in[key] = due_in.get(key, 0) + amount
            when = step(when)
            guard += 1

    # The standing monthly asks - plans, identical every month.
    budget = await get_or_create_budget(
        db, owner_user_id=owner_user_id, period_month=current_period_month()
    )
    budgets_monthly = sum(
        line.allocated_amount
        for line in await queries.budget_lines_for_period(
            db, budget.id, current_period_month()
        )
    )
    goals_monthly = sum(
        (
            await allocation.goal_allocations(
                db, owner_user_id=owner_user_id, today=today
            )
        ).values()
    )
    envelopes_monthly = sum(
        int(meta.monthly_credit * CADENCES[meta.cadence].monthly_factor)
        for account in await envelopes.list_envelopes(db, owner_user_id=owner_user_id)
        if (meta := envelopes.envelope_metadata(account.metadata_)) is not None
        and meta.auto_credit
        and meta.monthly_credit
    )
    everything_else = await uncovered_spending_rate(
        db, owner_user_id=owner_user_id, today=today, account_ids=account_ids
    )

    # The LEVEL under the rates: today's real cash for the selected
    # accounts, compounded through each month's net - a healthy rate
    # starting from an empty account still reads red where it should.
    account_rows, _total = await accounts.list_accounts(
        db, owner_user_id=owner_user_id, page_size=500
    )
    if account_ids is not None:
        allowed = set(account_ids)
        account_rows = [a for a in account_rows if a.id in allowed]
    cash = [
        a
        for a in account_rows
        if a.classification != "liability" and a.account_type in CASH_ACCOUNT_TYPES
    ]
    totals = await accounts.account_transaction_totals(
        db, owner_user_id=owner_user_id, account_ids=[a.id for a in cash]
    )
    running = display_cash_balance(cash, totals)

    outlook: list[BudgetMonthOutlook] = []
    for offset in range(months):
        month_start = add_months(first, offset)
        income_due = due_in.get((month_start.year, month_start.month, "in"), 0)
        bills_due = due_in.get((month_start.year, month_start.month, "out"), 0)
        month_net = (
            income_due
            - bills_due
            - budgets_monthly
            - goals_monthly
            - envelopes_monthly
            - everything_else
        )
        outlook.append(
            BudgetMonthOutlook(
                period_month=month_start.year * 100 + month_start.month,
                income_due=income_due,
                bills_due=bills_due,
                budgets=budgets_monthly,
                goals=goals_monthly,
                envelopes=envelopes_monthly,
                everything_else=everything_else,
                month_net=month_net,
                start_balance=running,
                end_balance=running + month_net,
            )
        )
        running += month_net
    return outlook


async def parse_budget_goal(
    db: AsyncSession, *, owner_user_id: int | None, text: str
) -> GoalParseResponse:
    """Deterministic (not LLM-backed) reading of a natural-language
    goal: "I wanna cut back on Starbucks" -> a payee match against the
    last 90 days of transactions, or a category match against the
    taxonomy, plus an explicit or default-50% cut fraction. Computes
    only - the frontend's Confirm step is what actually writes, via
    ``upsert_budget_line``.
    """

    casefold_text = text.casefold()

    percent_match = re.search(r"(\d+)\s*%", text)
    fraction = int(percent_match.group(1)) / 100 if percent_match else 0.5

    cutoff = date.today() - timedelta(days=90)
    filters = planning_queries.spend_filters(owner_user_id, cutoff)
    txn_rows = await queries.outflow_tuples(
        db, owner_user_id=owner_user_id, start=cutoff
    )
    payee_spend: dict[str, int] = defaultdict(int)
    payee_label: dict[str, str] = {}
    for _cat, merchant_name, original_description, name, amount, _stream in txn_rows:
        key = transaction_payee_key(merchant_name, original_description, name)
        if not key:
            continue
        payee_spend[key] += -amount
        payee_label.setdefault(key, merchant_name or name or key.title())

    # Match on the key's FIRST token, not the full label - the goal
    # text is short ("...on Starbucks") while the label can be a noisy
    # full descriptor ("STARBUCKS STORE 1234 NEW YORK NY"), so testing
    # "label in text" would almost never hit. The merchant name is
    # reliably the key's first token (transaction_payee_key's own
    # invariant). If several store-number variants share that first
    # token, the highest-spend one wins - the most representative
    # baseline for a single deterministic guess.
    candidates = [
        key
        for key in payee_label
        if len(key.split()[0]) >= 3 and key.split()[0].casefold() in casefold_text
    ]
    matched_payee_key = (
        max(candidates, key=lambda k: payee_spend[k]) if candidates else None
    )

    if matched_payee_key is not None:
        baseline_monthly = int(payee_spend[matched_payee_key] / 3)
        suggested_limit = round(baseline_monthly * fraction)
        label = payee_label[matched_payee_key]
        return GoalParseResponse(
            matched=True,
            target_type="payee",
            payee_key=matched_payee_key,
            payee_label=label,
            baseline_monthly=baseline_monthly,
            suggested_limit=suggested_limit,
            label=label,
            fraction=fraction,
        )

    category_rows = await categories.list_categories(db)
    matched_category = None
    for category in category_rows:
        leaf = category.name.rsplit(":", 1)[-1].strip()
        if len(leaf) >= 3 and leaf.casefold() in casefold_text:
            matched_category = category
            break

    if matched_category is not None:
        cat_filters = [
            *filters,
            FinanceTransaction.category_id == matched_category.id,
        ]
        cat_total = await queries.sum_amount_where(db, cat_filters)
        baseline_monthly = int(-cat_total / 3)
        suggested_limit = round(baseline_monthly * fraction)
        return GoalParseResponse(
            matched=True,
            target_type="category",
            category_id=matched_category.id,
            baseline_monthly=baseline_monthly,
            suggested_limit=suggested_limit,
            label=matched_category.name,
            fraction=fraction,
        )

    return GoalParseResponse(matched=False)
