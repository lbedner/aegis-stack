"""A budget you set once is a budget, not a monthly chore.

Allocations are keyed by period, so every month starts empty unless
something carries the last one forward. Nothing did: on the 1st, a
carefully built budget silently became "everything else", and the only
way back was to type it all in again.

The rule: a period with no allocations of its own inherits the most
recent period that had them - amounts only, never spend - and the moment
it has any of its own, it is its own month and inheritance stops.
"""

from collections import Counter
from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.service import FinanceService

AUGUST = 202608
SEPTEMBER = 202609


def _flexible(summary) -> list:
    """The bucket that holds the limits a person chose."""
    return [
        line
        for bucket in summary.buckets
        if bucket.name == "flexible"
        for line in bucket.lines
    ]


async def _august_budget(svc: FinanceService) -> tuple[int, int]:
    groceries = await svc.get_or_create_category_from_hint("Food:Groceries")
    fuel = await svc.get_or_create_category_from_hint("Auto:Gas")
    for category_id, cents in ((groceries.id, 100_000), (fuel.id, 20_000)):
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=AUGUST,
            category_id=category_id,
            payee_key=None,
            payee_label=None,
            allocated_amount=cents,
        )
    return groceries.id, fuel.id


@pytest.mark.asyncio
async def test_a_new_month_inherits_the_last_one(svc: FinanceService) -> None:
    groceries, fuel = await _august_budget(svc)

    summary = await svc.budget_summary(
        owner_user_id=1, period_month=SEPTEMBER, today=date(2026, 9, 3)
    )

    allocated = {line.category_id: line.allocated_amount for line in _flexible(summary)}
    assert allocated.get(groceries) == 100_000, "the grocery envelope did not carry"
    assert allocated.get(fuel) == 20_000, "the fuel envelope did not carry"


@pytest.mark.asyncio
async def test_it_carries_the_amounts_and_not_the_spending(
    svc: FinanceService,
) -> None:
    await _august_budget(svc)

    summary = await svc.budget_summary(
        owner_user_id=1, period_month=SEPTEMBER, today=date(2026, 9, 3)
    )

    assert all(line.spent_amount == 0 for line in _flexible(summary)), (
        "last month's spending followed the envelope into the new month"
    )


@pytest.mark.asyncio
async def test_a_month_you_have_edited_is_left_alone(svc: FinanceService) -> None:
    """Inheritance seeds an empty month; it never argues with a choice."""
    _, fuel = await _august_budget(svc)
    await svc.upsert_budget_line(
        owner_user_id=1,
        period_month=SEPTEMBER,
        category_id=fuel,
        payee_key=None,
        payee_label=None,
        allocated_amount=5_000,
    )

    summary = await svc.budget_summary(
        owner_user_id=1, period_month=SEPTEMBER, today=date(2026, 9, 3)
    )

    allocated = {line.category_id: line.allocated_amount for line in _flexible(summary)}
    assert allocated == {fuel: 5_000}, (
        "September had its own budget and inheritance overrode it"
    )


@pytest.mark.asyncio
async def test_the_forecast_draws_one_envelope_per_category(
    svc: FinanceService,
) -> None:
    """Not one per month that ever had a budget.

    The forecast asked for every allocation the budget has ever held, so
    once two periods existed each category drew twice on the same day -
    and before any second period existed it was silently charging LAST
    month's envelope.
    """
    groceries, fuel = await _august_budget(svc)
    await svc.create_manual_account(
        name="Checking",
        account_type="checking",
        classification="asset",
        owner_user_id=1,
    )
    # Reading September seeds it from August: two periods, same envelopes.
    await svc.budget_summary(
        owner_user_id=1, period_month=SEPTEMBER, today=date(2026, 9, 3)
    )

    result = await svc.project_balances(
        owner_user_id=1, days=60, today=date(2026, 9, 3)
    )

    draws = [p for p in result.points if p.category is not None]
    per_category = Counter((p.name, p.date) for p in draws)
    repeated = {k: n for k, n in per_category.items() if n > 1}
    assert not repeated, f"the same envelope drawn more than once: {repeated}"


@pytest.mark.asyncio
async def test_the_forecast_sees_the_inherited_envelopes(svc: FinanceService) -> None:
    """Inheritance is a property of the budget, not of the page that
    happens to ask first.

    Only the summary carried the last period forward, so a projection
    opened before the budget tab walked the balance forward with no
    envelopes at all - the same month, two answers, depending on
    click order.
    """
    await _august_budget(svc)
    await svc.create_manual_account(
        name="Checking",
        account_type="checking",
        classification="asset",
        owner_user_id=1,
    )

    result = await svc.project_balances(
        owner_user_id=1, days=40, today=date(2026, 9, 3)
    )

    drawn = {p.category for p in result.points if p.category is not None}
    assert drawn == {"Food:Groceries", "Auto:Gas"}, "the inherited envelopes never drew"


@pytest.mark.asyncio
async def test_the_month_strip_sees_the_inherited_envelopes(
    svc: FinanceService,
) -> None:
    await _august_budget(svc)

    outlook = await svc.budget_month_outlook(
        owner_user_id=1, months=2, today=date(2026, 9, 3)
    )

    assert outlook[0].budgets == 120_000, "the strip planned a month with no budget"


@pytest.mark.asyncio
async def test_two_pages_opening_the_month_at_once_do_not_collide(
    svc: FinanceService,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inheritance seeds a month on first read, and the dashboard opens
    several panels at once.

    Each of them asks the same question of the same empty period, so two
    can both see "no lines here" and both try to seed it. The unique
    index on (budget, category, period) means the loser's insert raises;
    it has to read the winner's rows instead of failing the request.
    """
    from app.services.finance.domains.planning.budgets import lines, queries

    groceries, _fuel = await _august_budget(svc)
    # September as the loser sees it: already seeded by whoever got there
    # first, but this caller's emptiness check happened before that.
    await svc.budget_summary(
        owner_user_id=1, period_month=SEPTEMBER, today=date(2026, 9, 3)
    )
    real_lines_for_period = queries.budget_lines_for_period
    calls = {"n": 0}

    async def looks_empty_once(db, budget_id, period_month):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            return []
        return await real_lines_for_period(db, budget_id, period_month)

    monkeypatch.setattr(queries, "budget_lines_for_period", looks_empty_once)

    budget = await lines.get_or_create_budget(
        async_db_session, owner_user_id=1, period_month=SEPTEMBER
    )
    carried = await lines.lines_in_force(
        async_db_session, budget_id=budget.id, period_month=SEPTEMBER
    )

    allocated = {line.category_id: line.allocated_amount for line in carried}
    assert allocated.get(groceries) == 100_000, (
        "the losing caller returned nothing instead of the rows already there"
    )
