"""The projection honours the dialog-wide account filter.

The forecast walks today's cash balance forward through scheduled bills.
Narrowing the view to one card and leaving the forecast global gives a
balance line for accounts you are not looking at - the number moves for
reasons that are off screen.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.service import FinanceService
from tests.services._finance_factories import declare_bill, seed_stream


async def _bill(svc, db, account_id, name, cents):
    await declare_bill(
        svc, db, account_id, name, [date(2026, m, 5) for m in range(1, 8)], cents=cents
    )


class TestProjectionAccountFilter:
    @pytest.mark.asyncio
    async def test_it_only_walks_the_accounts_you_are_viewing(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
        )
        savings = await svc.create_manual_account(
            name="Savings",
            account_type="savings",
            classification="asset",
            owner_user_id=1,
        )
        await _bill(svc, async_db_session, checking.id, "RENT", -180_000)
        await _bill(svc, async_db_session, savings.id, "STORAGE", -9_000)

        everything = await svc.project_balances(owner_user_id=1, days=120)
        just_checking = await svc.project_balances(
            owner_user_id=1, days=120, account_ids=[checking.id]
        )

        names = {p.name for p in everything.points}
        narrowed = {p.name for p in just_checking.points}
        assert "RENT" in names and "STORAGE" in names
        assert "RENT" in narrowed
        assert "STORAGE" not in narrowed

    @pytest.mark.asyncio
    async def test_no_filter_still_means_everything(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
        )
        await _bill(svc, async_db_session, checking.id, "RENT", -180_000)

        result = await svc.project_balances(owner_user_id=1, days=120)

        assert result.points


class TestAccountLessBills:
    """A bill with no account still belongs in the forecast.

    Hand-entered bills can be created without an account, and the filter
    I added asked ``stream.account_id not in allowed`` - which is always
    True for None. So narrowing to any account silently dropped every
    hand-entered bill from Projected. Confirmed live: "Betr Health",
    $5,000 twice a month, missing from the forecast.
    """

    @pytest.mark.asyncio
    async def test_it_projects_with_no_filter(self, svc: FinanceService) -> None:
        await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
        )
        await seed_stream(
            svc,
            name="Betr Health",
            direction="inflow",
            frequency="semi_monthly",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=None,
        )

        result = await svc.project_balances(
            owner_user_id=1, days=120, today=date(2026, 8, 2)
        )

        assert "Betr Health" in {p.name for p in result.points}

    @pytest.mark.asyncio
    async def test_narrowing_to_an_account_does_not_drop_it(
        self, svc: FinanceService
    ) -> None:
        checking = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
        )
        await seed_stream(
            svc,
            name="Betr Health",
            direction="inflow",
            frequency="semi_monthly",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=None,
        )

        result = await svc.project_balances(
            owner_user_id=1,
            days=120,
            today=date(2026, 8, 2),
            account_ids=[checking.id],
        )

        assert "Betr Health" in {p.name for p in result.points}
