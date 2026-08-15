"""Pausing a bill: a stated, self-expiring silence.

"I know I need to pause some investments for a few months." A pause is
``paused_until`` on the stream - lazy by design, nothing ever un-sets
it; the day the date passes, every consumer's comparison flips on its
own. One predicate feeds every surface, because the money math
disagreeing with itself is exactly what mute taught us: a muted bill
vanished from the forecast but kept counting in the Bills total, so the
header and the Projected tab told different stories. The pause work
fixes that inconsistency for mute in the same pass.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.categorize import generate_insights
from app.services.finance.categorize.insights import commitment_rollup, is_paused
from app.services.finance.finance_service import FinanceService
from app.services.finance.models import FinanceInsight, FinanceRecurringStream

TODAY = date(2026, 8, 9)


async def _account(svc):
    return await svc.create_manual_account(
        name="Checking", account_type="checking",
        classification="asset", owner_user_id=1,
    )


async def _bill(svc, account, name="M1 Finance", amount=30_000, direction="outflow"):
    return await svc.create_recurring_stream(
        owner_user_id=1, name=name, direction=direction,
        frequency="monthly", expected_amount=amount,
        next_expected_date=date(2026, 8, 15), account_id=account.id,
    )


class TestThePredicate:
    def _stream(self, until):
        return FinanceRecurringStream(
            owner_user_id=1, name="x", direction="outflow",
            frequency="monthly", source="user", paused_until=until,
        )

    def test_paused_while_the_date_is_ahead(self) -> None:
        assert is_paused(self._stream(date(2026, 11, 1)), TODAY) is True

    def test_expires_on_its_own_day(self) -> None:
        """"Until Nov 1" means active again ON Nov 1 - the lazy expiry
        that makes a scheduler job unnecessary."""
        assert is_paused(self._stream(TODAY), TODAY) is False

    def test_never_paused_without_a_date(self) -> None:
        assert is_paused(self._stream(None), TODAY) is False


class TestTheMoneyMathAgrees:
    """One pause, every surface: rollup, verdict, forecast, income."""

    @pytest.mark.asyncio
    async def test_a_paused_bill_leaves_the_rollup_and_the_verdict(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        stream = await _bill(svc, account)
        await svc.pause_recurring(
            stream.id, until=date(2026, 11, 1), owner_user_id=1
        )

        stats = (await svc.budget_summary(owner_user_id=1))["stats"]

        assert stats["fixed_total"] == 0
        assert stats["fixed_count"] == 0

    @pytest.mark.asyncio
    async def test_a_muted_bill_finally_leaves_the_rollup_too(
        self, async_db_session: AsyncSession
    ) -> None:
        """The pre-existing inconsistency: muting dropped a bill from the
        forecast but kept charging it in the Bills cell, so the header
        and Projected disagreed by the whole bill."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        stream = await _bill(svc, account)
        await svc.mute_recurring(stream.id, owner_user_id=1)
        await async_db_session.refresh(stream)

        rollup = commitment_rollup([stream])

        assert rollup["monthly_total"] == 0

    @pytest.mark.asyncio
    async def test_a_paused_bill_leaves_the_forecast(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        stream = await _bill(svc, account)
        await svc.pause_recurring(
            stream.id, until=date(2026, 11, 1), owner_user_id=1
        )

        projection = await svc.project_balances(
            owner_user_id=1, today=TODAY, days=30
        )

        assert projection.points == []

    @pytest.mark.asyncio
    async def test_the_pause_expires_into_the_forecast_by_itself(
        self, async_db_session: AsyncSession
    ) -> None:
        """The whole point of a dated pause over mute: November arrives
        and the bill walks back in without anyone touching anything."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        stream = await _bill(svc, account)
        await svc.pause_recurring(
            stream.id, until=date(2026, 9, 1), owner_user_id=1
        )

        projection = await svc.project_balances(
            owner_user_id=1, today=date(2026, 9, 2), days=30
        )

        assert len(projection.points) > 0

    @pytest.mark.asyncio
    async def test_paused_income_stops_counting(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        stream = await _bill(
            svc, account, name="Paycheck", amount=500_000, direction="inflow"
        )
        await svc.pause_recurring(
            stream.id, until=date(2026, 11, 1), owner_user_id=1
        )

        stats = (await svc.budget_summary(owner_user_id=1))["stats"]

        assert stats["income_total"] == 0

    @pytest.mark.asyncio
    async def test_a_paused_bill_is_never_nagged_as_missed(
        self, async_db_session: AsyncSession
    ) -> None:
        """A pause is "I know, stop telling me" - the missed-payment rule
        firing about it would be the nag the pause exists to silence."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        stream = await _bill(svc, account)
        stream.status = "mature"
        stream.next_expected_date = date(2026, 7, 1)  # overdue
        async_db_session.add(stream)
        await svc.pause_recurring(
            stream.id, until=date(2026, 11, 1), owner_user_id=1
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=TODAY, lookback_days=0
        )

        missed = (
            await async_db_session.exec(
                __import__("sqlmodel").select(FinanceInsight).where(
                    FinanceInsight.insight_type == "missed_recurring"
                )
            )
        ).all()
        assert missed == []


class TestPauseAndResume:
    @pytest.mark.asyncio
    async def test_pause_records_the_date_and_the_why(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        stream = await _bill(svc, account)

        paused = await svc.pause_recurring(
            stream.id,
            until=date(2026, 11, 1),
            note="waiting until the pool is paid off",
            owner_user_id=1,
        )

        assert paused.paused_until == date(2026, 11, 1)
        assert paused.metadata_["pause_note"] == "waiting until the pool is paid off"

    @pytest.mark.asyncio
    async def test_resume_clears_both(self, async_db_session: AsyncSession) -> None:
        """Future-you must not find a stale note explaining a pause that
        is no longer happening."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        stream = await _bill(svc, account)
        await svc.pause_recurring(
            stream.id, until=date(2026, 11, 1), note="why", owner_user_id=1
        )

        resumed = await svc.resume_recurring(stream.id, owner_user_id=1)

        assert resumed.paused_until is None
        assert "pause_note" not in resumed.metadata_

    @pytest.mark.asyncio
    async def test_wrong_owner_touches_nothing(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        stream = await _bill(svc, account)

        assert (
            await svc.pause_recurring(
                stream.id, until=date(2026, 11, 1), owner_user_id=99
            )
            is None
        )
