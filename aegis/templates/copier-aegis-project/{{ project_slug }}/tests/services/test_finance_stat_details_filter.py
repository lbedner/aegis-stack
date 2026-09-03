"""A header cell and its popup are the same number, filtered the same way.

The Budget tab's cells honour the account filter. Their click-through
detail fetched every stream the owner has, so narrowing to one account
showed "1 confirmed source / month, $10,000" above a popup listing four
sources adding to $14,050 - the cell and its own explanation disagreeing
on screen.
"""

from datetime import date

import pytest

from app.services.finance.service import FinanceService
from tests.services._finance_factories import seed_account, seed_stream

TODAY = date(2026, 9, 3)


async def _paycheck(svc: FinanceService, account_id: int, name: str, cents: int):
    return await seed_stream(
        svc,
        name=name,
        direction="inflow",
        frequency="monthly",
        expected_amount=cents,
        next_expected_date=date(2026, 9, 15),
        account_id=account_id,
    )


@pytest.mark.asyncio
async def test_the_income_popup_matches_the_income_cell(
    svc: FinanceService,
) -> None:
    mine = await seed_account(svc, name="Checking")
    theirs = await seed_account(svc, name="Other")
    await _paycheck(svc, mine.id, "BETR HEALTH", 1_000_000)
    await _paycheck(svc, theirs.id, "SOMEWHERE ELSE", 207_500)

    summary = await svc.budget_summary(
        owner_user_id=1, today=TODAY, account_ids=[mine.id]
    )
    details = await svc.budget_stat_details(
        owner_user_id=1, today=TODAY, account_ids=[mine.id]
    )

    assert [row.label for row in details.income] == ["BETR HEALTH"], (
        "the popup listed income from an account the filter excludes"
    )
    assert sum(row.value for row in details.income) == summary.stats.income_total
    assert summary.stats.income_count == 1, "the cell counted sources it cannot see"


@pytest.mark.asyncio
async def test_the_bills_popup_matches_the_bills_cell(svc: FinanceService) -> None:
    mine = await seed_account(svc, name="Checking")
    theirs = await seed_account(svc, name="Other")
    for account_id, name in ((mine.id, "RENT"), (theirs.id, "THEIR CAR")):
        await seed_stream(
            svc,
            name=name,
            direction="outflow",
            frequency="monthly",
            expected_amount=120_000,
            next_expected_date=date(2026, 9, 20),
            account_id=account_id,
        )

    details = await svc.budget_stat_details(
        owner_user_id=1, today=TODAY, account_ids=[mine.id]
    )

    assert [row.label for row in details.bills] == ["RENT"], (
        "the popup listed a bill from an account the filter excludes"
    )
