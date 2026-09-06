"""Walking money forward: today's cash balance through what is scheduled.

Three sources drain (or feed) the same timeline - recurring commitments,
budget lines, and goal contributions - and the interleaving is the point:
the running balance is only true if the draws land in the order money
actually moves.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import (
    CASH_ACCOUNT_TYPES,
    add_months,
)
from app.services.finance.domains.detection.insights.commitments import (
    is_commitment,
    is_paused,
)
from app.services.finance.domains.ledger import accounts
from app.services.finance.domains.ledger import queries as ledger_queries
from app.services.finance.domains.planning import allocation, budgets, goals, queries
from app.services.finance.domains.planning.recurring import queries as recurring_queries
from app.services.finance.domains.planning.recurring.schedule import occurrences
from app.services.finance.domains.planning.recurring.streams import (
    in_account_scope,
    list_recurring,
    payment_stream_ids,
    stream_category_names,
    transfer_stream_ids,
)
from app.services.finance.models import FinanceRecurringStream
from app.services.finance.schemas import (
    ProjectionPoint,
    ProjectionResponse,
)
from app.services.finance.utils import (
    current_period_month,
    display_cash_balance,
)

# Appended to the month that absorbs a prior overage. A budget line
# smaller than its allocation, with nothing to explain it, reads as a bug
# in the forecast rather than as the overage being made up.
_BUDGET_CARRY_NOTE = " (tightened by last month's overspend)"


def _period_month_for(day: date) -> int:
    """The YYYYMM period a date falls in."""
    return day.year * 100 + day.month


def _month_end(day: date) -> date:
    """The last day of ``day``'s month."""
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


async def project_balances(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    days: int = 180,
    today: date | None = None,
    account_ids: list[int] | None = None,
) -> ProjectionResponse:
    """Walk today's cash balance forward through scheduled bills/income.

    The starting point is the display balance of cash accounts
    (checking/savings/cash): the authoritative ``current_balance``
    when a balance write happened, else the register sum - the same
    rule the sidebar uses. Only COMMITMENTS project (the monthly-
    rollup gate), in both directions: detected merchant rhythms
    would fabricate a five-figure decline, and detected refund or
    transfer rhythms an equally fictional windfall. Muted and
    transfer streams are skipped. Of a stream's past-due
    occurrences only the latest is charged, carried to today (it is
    in flight); older ones are the insight rules' missed-payment
    chase, not the forecast's.
    """
    today = today or date.today()
    horizon = today + timedelta(days=days)

    account_rows, _ = await accounts.list_accounts(
        db, owner_user_id=owner_user_id, page_size=500
    )
    # The dialog-wide account filter reaches the forecast too: a
    # balance line that walks through bills on accounts you are not
    # viewing moves for reasons that are off screen.
    if account_ids is not None:
        allowed = set(account_ids)
        account_rows = [a for a in account_rows if a.id in allowed]
    cash = [
        a
        for a in account_rows
        if a.classification != "liability" and a.account_type in CASH_ACCOUNT_TYPES
    ]
    cash_ids = {a.id for a in cash}
    totals = await accounts.account_transaction_totals(
        db, owner_user_id=owner_user_id, account_ids=[a.id for a in cash]
    )
    start_balance = display_cash_balance(cash, totals)

    streams = await list_recurring(db, owner_user_id=owner_user_id)
    transfer_ids = await transfer_stream_ids(db, [s.id for s in streams])
    # Payment streams are the carve-out from the transfer exclusion:
    # the card autopay genuinely drains checking on a rhythm, and a
    # forecast that skips it runs optimistic by the whole payment
    # every month (confirmed live, ~$1,800/mo). The commitment gate
    # below still applies - a detector average poisoned by a one-off
    # paydown must not walk the forecast until the user pins it.
    payment_ids = await payment_stream_ids(db, list(transfer_ids))
    # (lands_on, stream, amount, due_on) - the two dates differ only
    # when an overdue occurrence is carried onto today.
    charges: list[tuple[date, FinanceRecurringStream, int, date]] = []
    for stream in streams:
        if (
            stream.is_muted
            or is_paused(stream, today)
            or (stream.id in transfer_ids and stream.id not in payment_ids)
        ):
            continue
        if not in_account_scope(stream, account_ids):
            continue
        # The walk starts from CASH, so only what moves cash belongs in
        # it. A subscription billed to a credit card leaves no cash on
        # the day it is charged - the card payment does that, and the
        # payment is a stream in this same walk. Counting both charges
        # the same dollars twice, which reads as a household that breaks
        # even on paper projecting steadily into the red. A stream with
        # no account is hand-entered and stays in: no account is no
        # statement about which one it hits.
        if stream.account_id is not None and stream.account_id not in cash_ids:
            continue
        # Both directions pass the commitment gate. Detected inflows
        # include refunds and brokerage-transfer rhythms; projecting
        # those as income fabricates a six-figure windfall. A real
        # paycheck (fixed amount at a paycheck cadence) passes the
        # gate on its own; a variable one gets in once its amount is
        # pinned in the edit dialog.
        if not is_commitment(stream):
            continue
        amount = stream.expected_amount or stream.average_amount or 0
        if amount <= 0:
            continue
        for due in occurrences(stream, today=today, through=horizon):
            charges.append((due.lands_on, stream, amount, due.due_on))

    # Budget lines are the OTHER half of what leaves an account:
    # everyday spending nobody bills you for. A line draws down once a
    # month, on the same day of the month, for as far as the horizon
    # reaches.
    #
    # Bills win where they overlap. A category a recurring bill
    # already pays is spending the forecast has counted once already,
    # and adding the budget on top charges it twice - which reads as a
    # pessimistic balance nobody can account for.
    billed_categories = {
        stream.category_id
        for _when, stream, _amount, _due in charges
        if stream.category_id is not None
    }
    # A card payment covers everything that was spent on that card, and
    # it carries no category of its own - so without this the rule above
    # sees nothing to suppress and a household that puts its groceries on
    # a card gets them charged twice: once as the envelope, once inside
    # the payment settling the statement.
    # Only the cards a PROJECTED payment settles. "Every credit card" would
    # silence the envelopes for a second card nobody is paying, and that
    # card's spending is exactly the cash the walk still has to find.
    projected_payments = [s.id for _w, s, _a, _d in charges if s.id in payment_ids]
    settled = await recurring_queries.settled_account_ids(db, projected_payments)
    billed_categories |= await card_paid_categories(
        db,
        owner_user_id=owner_user_id,
        today=today,
        card_ids=[
            a.id
            for a in account_rows
            if a.id is not None and a.id in settled and a.account_type == "credit_card"
        ],
        has_payment=bool(projected_payments),
    )
    budget_points = await budget_drawdowns(
        db,
        owner_user_id=owner_user_id,
        today=today,
        horizon=horizon,
        skip_categories=billed_categories,
    )

    charges.sort(key=lambda item: (item[0], item[1].name.casefold()))

    account_names = {a.id: a.name for a in account_rows}
    stream_categories = await stream_category_names(
        db, {s.id for _, s, _, _ in charges}
    )

    # One timeline: bills and budgets interleaved by date, so the
    # running balance is the order money actually moves.
    walk: list[tuple[date, str, int, dict[str, Any]]] = [
        (
            when,
            stream.name,
            amount if stream.direction == "inflow" else -amount,
            {
                "stream_id": stream.id,
                "direction": stream.direction,
                "account": account_names.get(stream.account_id),
                "category": stream_categories.get(stream.id),
                # Only when it differs from where it lands.
                "due_date": due if due < when else None,
            },
        )
        for when, stream, amount, due in charges
    ]
    walk.extend(budget_points)
    # Active goals drain the walk too - committing to a dream visibly
    # costs the chart.
    walk.extend(
        await goal_drawdowns(
            db, owner_user_id=owner_user_id, today=today, horizon=horizon
        )
    )
    walk.sort(key=lambda item: (item[0], item[1].casefold()))

    balance = start_balance
    points: list[ProjectionPoint] = []
    for when, name, signed, extra in walk:
        balance += signed
        points.append(
            ProjectionPoint(
                date=when,
                stream_id=extra.get("stream_id"),
                name=name,
                direction=extra.get("direction", "outflow"),
                amount=signed,
                balance=balance,
                account=extra.get("account"),
                category=extra.get("category"),
                due_date=extra.get("due_date"),
            )
        )
    return ProjectionResponse(
        as_of=today,
        horizon_days=days,
        start_balance=start_balance,
        upcoming_total=balance - start_balance,
        end_balance=balance,
        points=points,
        total=len(points),
    )


async def goal_drawdowns(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    today: date,
    horizon: date,
) -> list[tuple[date, str, int, dict[str, Any]]]:
    """Monthly goal contributions as forecast outflows, on the 1st
    (the day 's auto-contribute books). Paused/reached goals ask
    nothing (the pure-math contract). The linked-yield guard: a
    LINKED goal's synthetic month yields when a real inbound transfer
    to that account is already booked in that calendar month -
    without it, committing AND transferring double-drops the line.
    """
    goal_accounts = await goals.list_goals(db, owner_user_id=owner_user_id)
    if not goal_accounts:
        return []
    linked_ids = [
        a.id for a in goal_accounts if a.account_type != goals.GOAL_ACCOUNT_TYPE
    ]
    booked_months: dict[int, set[tuple[int, int]]] = {}
    if linked_ids:
        transfers = await queries.goal_transfer_dates(
            db,
            linked_ids,
            start=date(today.year, today.month, 1),
            end=horizon,
        )
        for account_id, when in transfers:
            booked_months.setdefault(account_id, set()).add((when.year, when.month))
    allocations = await allocation.goal_allocations(
        db, owner_user_id=owner_user_id, today=today
    )
    out: list[tuple[date, str, int, dict[str, Any]]] = []
    for account in goal_accounts:
        meta = goals.goal_metadata(account.metadata_)
        if meta is None:
            continue
        need = allocations.get(account.id, 0)
        if need <= 0:
            continue
        when = add_months(date(today.year, today.month, 1), 1)
        while when <= horizon:
            if (when.year, when.month) not in booked_months.get(account.id, set()):
                out.append(
                    (
                        when,
                        account.name,
                        -need,
                        {"direction": "outflow", "goal_account_id": account.id},
                    )
                )
            when = add_months(when, 1)
    return out


async def card_paid_categories(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    today: date,
    card_ids: list[int],
    has_payment: bool,
    lookback_days: int = 90,
) -> set[int]:
    """Categories already settled by a card payment in this walk.

    Empty unless a card payment is actually being projected: a card
    nobody pays settles nothing, and suppressing its envelopes would
    understate the month rather than double-count it.

    Reuses the same split-aware outflow read the budget header tallies,
    so "what was spent on this card" means the same thing on both
    surfaces.
    """
    if not has_payment or not card_ids:
        return set()
    rows = await budgets.queries.outflow_tuples(
        db,
        owner_user_id=owner_user_id,
        start=today - timedelta(days=lookback_days),
        end=today,
        account_ids=card_ids,
    )
    return {row[0] for row in rows if row[0] is not None}


async def budget_drawdowns(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    today: date,
    horizon: date,
    skip_categories: set[int],
) -> list[tuple[date, str, int, dict[str, Any]]]:
    """Monthly draws for each budget line, as forecast points.

    Dated on the same day of the month as today, which is a choice:
    everyday spending has no due date, and spreading it daily would
    bury the bills that DO. One visible step a month reads as "this is
    what I expect to spend", which is what a budget is.
    """
    this_period = current_period_month(today)
    budget = await budgets.get_or_create_budget(
        db, owner_user_id=owner_user_id, period_month=this_period
    )
    # This period's envelopes, not every period's: the forecast walks
    # forward from the budget in force, and older months are history.
    lines = [
        line
        for line in await budgets.lines_in_force(
            db, budget_id=budget.id, period_month=this_period
        )
        if line.allocated_amount > 0
    ]
    if not lines:
        return []
    line_category_ids = {
        line.category_id for line in lines if line.category_id is not None
    }
    names = await ledger_queries.category_names_by_id(db, line_category_ids)

    # What is LEFT of each month's envelope, not the whole of it. Money
    # already spent has left the account and is in the starting balance;
    # charging the allocation on top counts it twice, and every new
    # transaction widens the gap. Spend for ALL lines lands in two
    # queries (one grouped by category, one payee-key bucket), never one
    # query per line.
    start, end = budgets.month_bounds(_period_month_for(today))
    spent_by_category = await queries.spend_by_category(
        db,
        owner_user_id=owner_user_id,
        start=start,
        end=end,
        category_ids=line_category_ids - skip_categories,
    )
    spent_by_payee = await queries.spend_by_payee_key(
        db,
        owner_user_id=owner_user_id,
        start=start,
        end=end,
        payee_keys={
            line.payee_key
            for line in lines
            if line.category_id is None and line.payee_key
        },
    )

    out: list[tuple[date, str, int, dict[str, Any]]] = []
    for line in lines:
        if line.category_id is not None and line.category_id in skip_categories:
            continue
        label = (
            names.get(line.category_id)
            or getattr(line, "payee_label", None)
            or "Budget"
        )
        allocated = int(line.allocated_amount)
        extra = {"direction": "outflow", "category": names.get(line.category_id)}

        if line.category_id is not None:
            spent = spent_by_category.get(line.category_id, 0)
        elif line.payee_key:
            spent = spent_by_payee.get(line.payee_key, 0)
        else:
            spent = 0
        remaining = allocated - spent
        this_month = _month_end(today)
        if remaining > 0 and this_month <= horizon:
            # Dated at month END: it has not happened yet, so it must
            # not dent the line today. Dating these at ``today`` also
            # piled every budget line onto the first point of the walk.
            #
            # And only when the window reaches that date: the carry loop
            # below has always asked, but this one did not, so a one-day
            # projection on the 3rd showed the 30th's grocery envelope.
            out.append((this_month, label, -remaining, extra))

        # Overspending is not a write-off. The overage carries into the
        # next envelope as a TIGHTER budget, so the forecast shows it
        # being made up without anyone editing the budget. Only the
        # next month: you make it up once, then the envelope is clean.
        # Underspend carries nothing, because the remainder above
        # already assumes this month's envelope gets used.
        carry = min(0, remaining)
        when = _month_end(add_months(today, 1))
        first = True
        while when <= horizon:
            amount = max(0, allocated + carry) if first else allocated
            if amount > 0:
                name = label + (_BUDGET_CARRY_NOTE if first and carry else "")
                out.append((when, name, -amount, extra))
            first = False
            when = _month_end(add_months(when, 1))
    return out
