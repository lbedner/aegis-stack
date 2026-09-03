"""The month's allocation engine: what each goal asks, and what a
relative target resolves to.

The pure half is ``allocate_month`` - the month's code-owned figures in,
one ask per goal out, evaluated in priority order. Every consumer
(month_net, the projection drawdowns, auto-contribute, the API's
monthly_need) reads THIS, never a goal's raw declared amount, so the
whole app can only disagree with itself if this function is wrong.

Targets resolve here too, because a relative target is a question about
the month's figures rather than about the goal: "six months of expenses"
is six times the committed figure the budget header already shows. A
goal's stored cents are the last resolved value and the fallback for a
book too new to have figures; the rule is the authority.

Split out of ``goals.py``, which owns the metadata contract and the
per-goal math. This module depends on that one, never the reverse.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import add_months
from app.services.finance.domains.detection.insights.commitments import (
    commitment_rollup,
)
from app.services.finance.domains.ledger import queries as ledger_queries
from app.services.finance.domains.planning import recurring
from app.services.finance.domains.planning.goals import (
    GoalMeta,
    goal_metadata,
    goal_monthly_need,
    list_goals,
)
from app.services.finance.utils import (
    current_period_month,
    monthly_income,
)


class MonthlyFigures(BaseModel):
    """The month's code-owned inputs the engine evaluates against.

    ``income_total`` is the confirmed-commitment monthly income (the same
    gate budget_summary applies); ``committed`` is what the month already
    owes before goals - bills monthly-equivalent plus budget allocations.
    """

    model_config = ConfigDict(frozen=True)

    income_total: int
    committed: int
    # What a fund sized in months has to survive on, per cash account.
    # Two things make this narrower than ``committed``: it is per-account
    # (a second checking account's bills are not this household's run
    # rate), and it drops card/loan PAYMENT streams, because the swipes
    # they settle are already counted - the same carve-out the Bills
    # total documents. ``budget_allocated`` rides on top of any scope:
    # a budget line is household spending whichever account pays it.
    expense_base_by_account: dict[int, int] = {}
    # Bills nobody attached to an account. They are real money and count
    # toward the whole book's run rate; they just cannot answer a
    # question about one account, so a narrowed scope leaves them out.
    expense_base_unattached: int = 0
    budget_allocated: int = 0
    # What actually left each account per month over the trailing window.
    # Preferred over the declared base wherever there is history: a book
    # spends plenty it never wrote down as a bill, and a fund sized on
    # the declarations alone is short by everything undeclared.
    observed_by_account: dict[int, int] = {}

    def expenses_for(self, scope: tuple[int, ...] = ()) -> int:
        """The monthly run rate a relative target resolves against. An
        empty scope means every cash account, which is the default a goal
        gets until someone narrows it."""
        measured = self.observed_by_account
        if scope:
            measured = {k: v for k, v in measured.items() if k in scope}
        if measured:
            # Measured beats declared, and stands alone: budget lines are
            # a plan for spending the transactions already record.
            return sum(measured.values())
        if scope:
            named = {
                k: v for k, v in self.expense_base_by_account.items() if k in scope
            }
            return sum(named.values()) + self.budget_allocated
        return (
            sum(self.expense_base_by_account.values())
            + self.expense_base_unattached
            + self.budget_allocated
        )


def target_for_rule(
    *,
    rule: str,
    factor: int | None,
    figures: MonthlyFigures,
    scope: tuple[int, ...] = (),
) -> int:
    """The cents a relative rule resolves to, or 0 when this month's
    figures cannot answer yet. The single home of the arithmetic: the
    write path sizes a new goal with it, the read path re-resolves with
    it, and the two cannot drift."""
    if rule == "months_of_expenses":
        return (factor or 0) * figures.expenses_for(scope)
    return 0


def resolve_target(meta: GoalMeta, figures: MonthlyFigures) -> int:
    """The goal's target in cents as of this month's figures.

    ``months_of_expenses`` is the factor times the month's run rate on
    the accounts the goal names: what actually left them, minus CARD
    payments (the swipes they settle are already counted) but including
    loan payments, which nothing else records. A book with nothing to
    measure yet falls back to the stored cents rather than resolving to
    zero: a brand-new plan must not render a $0 target it never asked
    for.
    """
    derived = target_for_rule(
        rule=meta.target_rule,
        factor=meta.target_factor,
        figures=figures,
        scope=tuple(meta.target_scope or ()),
    )
    return derived or meta.target_amount


def resolved_meta(meta: GoalMeta, figures: MonthlyFigures) -> GoalMeta:
    """``meta`` with a relative target resolved into its cents.

    Everything downstream - progress, the ask, the ETA - reads
    ``target_amount``, so resolving once here is what keeps a derived
    goal from needing special cases in any of them.
    """
    resolved = resolve_target(meta, figures)
    if resolved == meta.target_amount:
        return meta
    return meta.model_copy(update={"target_amount": resolved})


def allocate_month(
    figures: MonthlyFigures,
    goals: list[tuple[str, GoalMeta, int]],
    *,
    today: date | None = None,
) -> dict[str, int]:
    """This month's ask per goal, evaluated in priority order.

    ``goals`` rows are (key, meta, balance). Rules: ``fixed`` keeps the
    original per-goal logic (target-date derived, else declared);
    ``percent_income`` is income x bps/10000; ``surplus`` sweeps what the
    month has left AFTER committed spending and every allocation above
    it, floored at zero. Every ask caps at remaining-to-target, against
    the RESOLVED target - a fund sized in months of expenses asks again
    when expenses grow. Paused/reached goals ask nothing. Deterministic:
    priority then key.
    """
    today = today or date.today()
    asks: dict[str, int] = {}
    room = figures.income_total - figures.committed
    for key, stored, balance in sorted(
        goals, key=lambda row: (row[1].priority, row[0].casefold())
    ):
        meta = resolved_meta(stored, figures)
        remaining = meta.target_amount - balance
        if meta.status != "active" or remaining <= 0:
            asks[key] = 0
            continue
        if meta.contribution_kind == "percent_income":
            ask = figures.income_total * (meta.contribution_bps or 0) // 10_000
        elif meta.contribution_kind == "surplus":
            ask = max(0, room)
        else:
            ask = goal_monthly_need(meta, balance=balance, today=today)
        ask = max(0, min(ask, remaining))
        asks[key] = ask
        room -= ask
    return asks


def asks_by_account(
    accounts: list[Any], figures: MonthlyFigures, *, today: date
) -> dict[int, int]:
    """This month's ask per goal ACCOUNT ID. The one place account rows
    become engine rows, so the budget header and the goals API cannot
    build them differently."""
    rows = [
        (str(account.id), meta, account.current_balance or 0)
        for account in accounts
        if (meta := goal_metadata(account.metadata_)) is not None
    ]
    return {
        int(key): ask for key, ask in allocate_month(figures, rows, today=today).items()
    }


OBSERVED_WINDOW_MONTHS = 3


async def observed_run_rate(
    db: AsyncSession, *, owner_user_id: int | None, today: date
) -> dict[int, int]:
    """Cents a month actually spent from each account over the trailing
    window - the measured half of the run rate.

    Three months is short enough to track a life that changed and long
    enough that one heavy week does not set the number. A partial window
    still divides by the full three: a book two months old should read
    as spending less per month, not as spending more.
    """
    start = add_months(today, -OBSERVED_WINDOW_MONTHS)
    # Whole streams, not flagged transactions: a card payment that was
    # never matched carries no transfer flag, and counting it puts the
    # payment on top of the swipes it settles.
    streams = await recurring.list_recurring(db, owner_user_id=owner_user_id)
    stream_ids = [s.id for s in streams if s.id is not None]
    card_streams = await recurring.card_payment_stream_ids(db, stream_ids)
    # A matched loan payment is a transfer, and the blanket transfer
    # filter would drop it - but nothing else records that money leaving,
    # so it has to come back through. Card payments stay out: the swipes
    # they settle are already in the window.
    loan_streams = await recurring.payment_stream_ids(db, stream_ids) - card_streams
    rows = await ledger_queries.outflow_by_account_in_window(
        db,
        owner_user_id=owner_user_id,
        start=start,
        end=today,
        exclude_stream_ids=list(card_streams),
        include_transfer_stream_ids=list(loan_streams),
    )
    return {
        account_id: total // OBSERVED_WINDOW_MONTHS
        for account_id, total in rows
        if total > 0
    }


def goal_shortfall(figures: MonthlyFigures, asks: dict[str, int]) -> int:
    """Cents the month's goals ask for and the month does not have.

    Only ``fixed`` and ``percent_income`` can produce one: ``surplus``
    sweeps what is left and floors at zero, so it cannot overspend by
    construction. Deliberately NOT a clamp - a goal that says $1,405
    books $1,405, because a plan quietly reduced to fit is a plan the
    user never made. This is the number that lets a surface say so.
    """
    room = max(0, figures.income_total - figures.committed)
    return max(0, sum(asks.values()) - room)


async def month_figures(
    db: AsyncSession, *, owner_user_id: int | None, today: date
) -> MonthlyFigures:
    """This month's income and committed totals, on the same footing the
    budget header shows them: confirmed monthly income, and bills
    monthly-equivalent plus this period's budget allocations."""
    from app.services.finance.domains.planning import budgets

    streams = await recurring.list_recurring(db, owner_user_id=owner_user_id)
    income_total, _count = monthly_income(streams)
    rollup = commitment_rollup(streams, today=today)
    # The per-account run rate, minus CARD payments only: an autopay and
    # the swipes it settles are the same money seen twice, and a fund
    # sized on both is sized on a number that never existed. Loan
    # payments stay - a mortgage transfer is the only record that expense
    # has, and a fund that skips it is short by a mortgage a month.
    transfer_ids = await recurring.transfer_stream_ids(db, [s.id for s in streams])
    card_payment_ids = await recurring.card_payment_stream_ids(db, list(transfer_ids))
    spending = [s for s in streams if s.id not in card_payment_ids]
    by_account: dict[int, int] = {}
    for account_id in {s.account_id for s in spending if s.account_id is not None}:
        owed = commitment_rollup(
            [s for s in spending if s.account_id == account_id], today=today
        )
        by_account[account_id] = owed["monthly_total"]
    unattached = commitment_rollup(
        [s for s in spending if s.account_id is None], today=today
    )["monthly_total"]
    period = current_period_month(today)
    budget = await budgets.get_or_create_budget(
        db, owner_user_id=owner_user_id, period_month=period
    )
    allocated = sum(
        line.allocated_amount
        for line in await budgets.lines_in_force(
            db, budget_id=budget.id, period_month=period
        )
    )
    observed = await observed_run_rate(db, owner_user_id=owner_user_id, today=today)
    return MonthlyFigures(
        income_total=income_total,
        committed=rollup["monthly_total"] + allocated,
        expense_base_by_account=by_account,
        expense_base_unattached=unattached,
        budget_allocated=allocated,
        observed_by_account=observed,
    )


async def goal_allocations(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    today: date,
    figures: MonthlyFigures | None = None,
) -> dict[int, int]:
    """This month's evaluated ask per goal account id - the engine run
    once over the whole goal set, against the same income/committed
    figures the budget header shows. A caller holding those figures
    already (the goals listing resolves targets from them) passes them
    in rather than paying for the same two queries twice."""
    goal_accounts = await list_goals(db, owner_user_id=owner_user_id)
    if not goal_accounts:
        return {}
    if figures is None:
        figures = await month_figures(db, owner_user_id=owner_user_id, today=today)
    return asks_by_account(goal_accounts, figures, today=today)
