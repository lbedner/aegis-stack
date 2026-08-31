"""Overdue occurrences: money still in flight is not money that vanished.

The forecast fast-forwards each stream past occurrences dated before
today. Skipping ALL of them reads a one-day-late paycheck as "you are
$5,000 poorer for the next two weeks" - the walk starts from a balance
the check never reached and never charges the check anywhere. The rule:
the LATEST missed occurrence carries to today (it is in flight - a late
check, a bill due but not yet drafted); everything older is a stale
stream's echo, already in the starting balance or the insight rules'
missed-payment chase, and stays skipped.
"""

from datetime import date

import pytest

from app.services.finance.service import FinanceService
from tests.services._finance_factories import seed_account, seed_stream

TODAY = date(2026, 8, 31)


async def _paycheck(svc: FinanceService, *, next_expected: date):
    account = await seed_account(svc)
    return await seed_stream(
        svc,
        name="BETR HEALTH PAYROLL",
        direction="inflow",
        frequency="semi_monthly",
        expected_amount=500_000,
        next_expected_date=next_expected,
        account_id=account.id,
    )


class TestOverdueOccurrencesCarryToToday:
    @pytest.mark.asyncio
    async def test_the_latest_missed_occurrence_lands_on_today(
        self, svc: FinanceService
    ) -> None:
        """Next-expected 8/15, today 8/31: the 8/15 check was received
        (it is inside the starting balance), the 8/30 check is in
        flight. Exactly one carried occurrence, dated today."""
        await _paycheck(svc, next_expected=date(2026, 8, 15))

        result = await svc.project_balances(owner_user_id=1, days=30, today=TODAY)

        paydays = [p.date for p in result.points if p.name == "BETR HEALTH PAYROLL"]
        assert paydays.count(TODAY) == 1
        assert date(2026, 8, 15) not in paydays
        carried = next(p for p in result.points if p.date == TODAY)
        assert carried.amount == 500_000
        assert carried.direction == "inflow"

    @pytest.mark.asyncio
    async def test_the_cadence_continues_past_the_carried_one(
        self, svc: FinanceService
    ) -> None:
        """The carry replaces nothing: 9/14 and 9/29 still project."""
        await _paycheck(svc, next_expected=date(2026, 8, 15))

        result = await svc.project_balances(owner_user_id=1, days=30, today=TODAY)

        paydays = [p.date for p in result.points if p.name == "BETR HEALTH PAYROLL"]
        assert paydays == [TODAY, date(2026, 9, 14), date(2026, 9, 29)]

    @pytest.mark.asyncio
    async def test_an_overdue_bill_carries_too(self, svc: FinanceService) -> None:
        """Both directions: a bill due 8/19 and not yet drafted still
        drains today's line, not nowhere."""
        account = await seed_account(svc)
        await seed_stream(
            svc,
            name="ATT",
            direction="outflow",
            frequency="monthly",
            expected_amount=24_300,
            next_expected_date=date(2026, 8, 19),
            account_id=account.id,
        )

        result = await svc.project_balances(owner_user_id=1, days=30, today=TODAY)

        due = [p.date for p in result.points if p.name == "ATT"]
        assert due == [TODAY, date(2026, 9, 19)]

    @pytest.mark.asyncio
    async def test_a_future_stream_is_untouched(self, svc: FinanceService) -> None:
        await _paycheck(svc, next_expected=date(2026, 9, 14))

        result = await svc.project_balances(owner_user_id=1, days=30, today=TODAY)

        paydays = [p.date for p in result.points if p.name == "BETR HEALTH PAYROLL"]
        assert paydays == [date(2026, 9, 14), date(2026, 9, 29)]

    @pytest.mark.asyncio
    async def test_only_the_latest_miss_carries_from_deep_overdue(
        self, svc: FinanceService
    ) -> None:
        """Months stale (next-expected 5/10): one carried occurrence,
        not four - the old misses are already history, not forecast."""
        account = await seed_account(svc)
        await seed_stream(
            svc,
            name="STALE GYM",
            direction="outflow",
            frequency="monthly",
            expected_amount=5_000,
            next_expected_date=date(2026, 5, 10),
            account_id=account.id,
        )

        result = await svc.project_balances(owner_user_id=1, days=30, today=TODAY)

        due = [p.date for p in result.points if p.name == "STALE GYM"]
        assert due == [TODAY, date(2026, 9, 10)]

    @pytest.mark.asyncio
    async def test_a_missed_one_time_bill_still_does_not_carry(
        self, svc: FinanceService
    ) -> None:
        """One-time stays one-time: never stepped, never re-charged from
        the past - chasing it is the insight rules' job."""
        account = await seed_account(svc)
        await seed_stream(
            svc,
            name="PAY BACK BOB",
            direction="outflow",
            frequency="once",
            expected_amount=50_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )

        result = await svc.project_balances(owner_user_id=1, days=30, today=TODAY)

        assert not [p for p in result.points if p.name == "PAY BACK BOB"]
