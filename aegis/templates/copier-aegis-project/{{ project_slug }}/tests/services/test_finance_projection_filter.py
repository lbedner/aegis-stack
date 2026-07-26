"""The projection honours the dialog-wide account filter.

The forecast walks today's cash balance forward through scheduled bills.
Narrowing the view to one card and leaving the forecast global gives a
balance line for accounts you are not looking at - the number moves for
reasons that are off screen.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.categorize import declare_recurring
from app.services.finance.finance_service import FinanceService


async def _bill(svc, db, account_id, name, cents):
    txns = [
        await svc.create_transaction(
            account_id=account_id, amount=cents, txn_date=date(2026, m, 5),
            owner_user_id=1, name=name,
        )
        for m in range(1, 8)
    ]
    await declare_recurring(db, [t.id for t in txns], owner_user_id=1)


class TestProjectionAccountFilter:
    @pytest.mark.asyncio
    async def test_it_only_walks_the_accounts_you_are_viewing(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        checking = await svc.create_manual_account(
            name="Checking", account_type="checking",
            classification="asset", owner_user_id=1,
        )
        savings = await svc.create_manual_account(
            name="Savings", account_type="savings",
            classification="asset", owner_user_id=1,
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
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        checking = await svc.create_manual_account(
            name="Checking", account_type="checking",
            classification="asset", owner_user_id=1,
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
    async def test_it_projects_with_no_filter(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        await svc.create_manual_account(
            name="Checking", account_type="checking",
            classification="asset", owner_user_id=1,
        )
        await svc.create_recurring_stream(
            owner_user_id=1, name="Betr Health", direction="inflow",
            frequency="semi_monthly", expected_amount=500_000,
            next_expected_date=date(2026, 8, 15), account_id=None,
        )

        result = await svc.project_balances(
            owner_user_id=1, days=120, today=date(2026, 8, 2)
        )

        assert "Betr Health" in {p.name for p in result.points}

    @pytest.mark.asyncio
    async def test_narrowing_to_an_account_does_not_drop_it(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        checking = await svc.create_manual_account(
            name="Checking", account_type="checking",
            classification="asset", owner_user_id=1,
        )
        await svc.create_recurring_stream(
            owner_user_id=1, name="Betr Health", direction="inflow",
            frequency="semi_monthly", expected_amount=500_000,
            next_expected_date=date(2026, 8, 15), account_id=None,
        )

        result = await svc.project_balances(
            owner_user_id=1, days=120, today=date(2026, 8, 2),
            account_ids=[checking.id],
        )

        assert "Betr Health" in {p.name for p in result.points}
