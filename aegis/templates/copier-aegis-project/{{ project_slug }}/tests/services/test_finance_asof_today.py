"""``today`` means today, not whenever the server happens to run.

Every forward-looking call takes an explicit ``today`` - it is how the
projection answers "what if I ask about last month" and how these tests
stay stable across a month boundary. But the budget period underneath was
read off the server clock, so the walk was dated from the caller's date
while spending the wrong month's envelopes. The mismatch is invisible
whenever the two agree, which is most of the time, and wrong for exactly
the cases the parameter exists to serve.
"""

from datetime import date

import pytest

from app.services.finance.service import FinanceService

# Deliberately not the month these tests run in: the server clock and the
# asked-about date have to be able to disagree for the rule to be visible.
ASKED = date(2026, 7, 15)
ASKED_PERIOD = 202607
# A month between the one asked about and any month this can run in.
# Reading the server's clock lands on an empty period, which inherits
# from THIS one - the wrong envelope, and a different category, so the
# mistake cannot hide behind two equal amounts.
NEXT_PERIOD = 202608


async def _two_budgets(svc: FinanceService) -> None:
    """Two months, two different envelopes."""
    for period, hint, cents in (
        (ASKED_PERIOD, "Food:Groceries", 100_000),
        (NEXT_PERIOD, "Auto:Gas", 50_000),
    ):
        category = await svc.get_or_create_category_from_hint(hint)
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=period,
            category_id=category.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=cents,
        )


@pytest.mark.asyncio
async def test_the_projection_spends_the_asked_about_month(
    svc: FinanceService,
) -> None:
    await _two_budgets(svc)
    await svc.create_manual_account(
        name="Checking",
        account_type="checking",
        classification="asset",
        owner_user_id=1,
    )

    result = await svc.project_balances(owner_user_id=1, days=40, today=ASKED)

    draws = {p.name: p.amount for p in result.points if p.category is not None}
    assert draws == {"Food:Groceries": -100_000}, (
        "the walk spent a month it was not asked about"
    )


@pytest.mark.asyncio
async def test_the_month_strip_plans_the_asked_about_month(
    svc: FinanceService,
) -> None:
    await _two_budgets(svc)

    outlook = await svc.budget_month_outlook(owner_user_id=1, months=2, today=ASKED)

    assert outlook[0].budgets == 100_000
