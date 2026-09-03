"""The projection stops where the horizon does.

Ask for one day and you should see one day. The budget lines are the part
that forgot: a month's remaining envelope is dated at month end, which is
usually outside a short window, and it was appended without asking whether
the horizon reached it. Picking "1d" on September 3rd showed September
30th's grocery budget.
"""

from datetime import date, timedelta

import pytest

from app.services.finance.service import FinanceService

TODAY = date(2026, 9, 3)
MONTH = TODAY.year * 100 + TODAY.month


async def _budgeted(svc: FinanceService, name: str, cents: int) -> None:
    category = await svc.get_or_create_category_from_hint(name)
    await svc.upsert_budget_line(
        owner_user_id=1,
        period_month=MONTH,
        category_id=category.id,
        payee_key=None,
        payee_label=None,
        allocated_amount=cents,
    )


@pytest.mark.asyncio
async def test_a_one_day_window_holds_nothing_from_month_end(
    svc: FinanceService,
) -> None:
    await svc.create_manual_account(
        name="Checking",
        account_type="checking",
        classification="asset",
        owner_user_id=1,
    )
    await _budgeted(svc, "Food:Groceries", 100_000)

    result = await svc.project_balances(owner_user_id=1, days=1, today=TODAY)

    horizon = TODAY + timedelta(days=1)
    beyond = [point for point in result.points if point.date > horizon]
    assert not beyond, (
        f"points past the horizon: {[(str(p.date), p.name) for p in beyond]}"
    )


@pytest.mark.asyncio
async def test_a_window_that_reaches_month_end_still_includes_it(
    svc: FinanceService,
) -> None:
    """The fix must not lose the budget line, only date-bound it."""
    await svc.create_manual_account(
        name="Checking",
        account_type="checking",
        classification="asset",
        owner_user_id=1,
    )
    await _budgeted(svc, "Food:Groceries", 100_000)

    result = await svc.project_balances(owner_user_id=1, days=60, today=TODAY)

    names = [point.name for point in result.points]
    assert any("Groceries" in n for n in names), (
        f"the budget draw disappeared entirely: {names}"
    )
