"""One-time bills: "I gotta pay someone back."

A real obligation with a date and an amount, but no cadence - paying Bob
$500 on the 15th. It belongs in Bills (it IS a bill: it must be
remembered, forecast, and chased if missed), so it rides the recurring
stream with frequency ``once`` rather than a parallel table. What makes
it different is everything cadence-shaped: it projects exactly one
occurrence, never steps, and contributes nothing to the monthly rollup.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection.insights import commitment_rollup
from app.services.finance.service import FinanceService
from tests.services._finance_factories import seed_account as _account
from tests.services._finance_factories import seed_stream


async def _once_bill(svc, *, due=date(2026, 8, 15), amount=50_000):
    account = await _account(svc)
    return await seed_stream(
        svc,
        name="Pay back Bob",
        frequency="once",
        expected_amount=amount,
        next_expected_date=due,
        account_id=account.id,
    )


class TestAOneTimeBill:
    @pytest.mark.asyncio
    async def test_it_can_be_created(self, svc: FinanceService) -> None:
        stream = await _once_bill(svc)
        assert stream.frequency == "once"
        assert stream.next_expected_date == date(2026, 8, 15)

    @pytest.mark.asyncio
    async def test_it_projects_exactly_one_occurrence(
        self, svc: FinanceService
    ) -> None:
        """The whole point of putting it in Bills: the forecast dips by
        $500 on the 15th - once. A cadence bill would repeat to the
        horizon; this must not."""
        await _once_bill(svc)

        result = await svc.project_balances(
            owner_user_id=1, days=365, today=date(2026, 8, 8)
        )

        hits = [p for p in result.points if p.name == "Pay back Bob"]
        assert len(hits) == 1
        assert hits[0].date == date(2026, 8, 15)
        assert hits[0].amount == -50_000

    @pytest.mark.asyncio
    async def test_a_past_one_is_not_recharged(self, svc: FinanceService) -> None:
        """Same rule every stream follows: the forecast never re-charges
        the past. Chasing a missed payment is the insight rules' job."""
        await _once_bill(svc, due=date(2026, 7, 1))

        result = await svc.project_balances(
            owner_user_id=1, days=365, today=date(2026, 8, 8)
        )

        assert not [p for p in result.points if p.name == "Pay back Bob"]

    @pytest.mark.asyncio
    async def test_it_stays_out_of_the_monthly_rollup(
        self, svc: FinanceService
    ) -> None:
        """ "About $X/month in recurring bills" answers what life costs
        per month. A one-off debt is not a monthly cost, and folding
        $500 into that headline at any weight would be wrong at every
        weight."""
        stream = await _once_bill(svc)

        rollup = commitment_rollup([stream])

        assert rollup["monthly_total"] == 0

    @pytest.mark.asyncio
    async def test_editing_to_once_does_not_invent_a_date(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The derive-on-edit rule steps a cadence forward from the last
        occurrence - "once" has no step, and inventing a due date for a
        debt would be guessing when you owe someone money."""
        account = await _account(svc)
        txn = await svc.create_transaction(
            account_id=account.id,
            amount=-50_000,
            txn_date=date(2026, 8, 1),
            owner_user_id=1,
            name="BOB",
        )
        from app.services.finance.domains.detection import declare_recurring

        await declare_recurring(async_db_session, [txn.id], owner_user_id=1)
        stream = (await svc.list_recurring(owner_user_id=1))[0]
        assert stream.next_expected_date is None

        updated = await svc.update_recurring(
            stream.id, owner_user_id=1, frequency="once"
        )

        assert updated is not None
        assert updated.frequency == "once"
        assert updated.next_expected_date is None
