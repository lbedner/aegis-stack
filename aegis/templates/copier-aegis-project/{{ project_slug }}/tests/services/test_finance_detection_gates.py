"""What detection is allowed to call a recurring stream.

The old rule was: 3+ transactions whose MEDIAN gap lands within +/-20% of
a canonical cadence. Both halves are too weak on real data.

Stewart's Shops - a convenience store - was detected as a yearly
subscription at 90% confidence from four visits with gaps of 2044, 430
and 17 days and amounts from $2.69 to $85.32. The median gap (430) fell
inside +/-20% of a year, because 20% of 365 is a 73-day window. Across
325 streams, 55% had a biggest gap at least 5x their smallest: no rhythm
at all.
"""

from datetime import date, timedelta

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.categorize import detect_recurring
from app.services.finance.categorize.recurring import _frequency_for, _rhythm_ratio
from app.services.finance.finance_service import FinanceService


async def _account(svc: FinanceService):
    return await svc.create_manual_account(
        name="Checking", account_type="checking",
        classification="asset", owner_user_id=1,
    )


async def _spend(svc, account_id, days: list[date], cents: int = -2_500, name="ACME"):
    return [
        await svc.create_transaction(
            account_id=account_id, amount=cents, txn_date=day,
            owner_user_id=1, name=name,
        )
        for day in days
    ]


class TestCadenceTolerance:
    def test_a_year_no_longer_has_a_five_month_window(self) -> None:
        """+/-20% of 365 is +/-73 days, so anything from 292 to 438 days
        was "yearly". That is what caught Stewart's at a 430-day median."""
        assert _frequency_for(430) is None
        assert _frequency_for(365) == "annually"
        assert _frequency_for(380) == "annually"  # still generous

    def test_short_cadences_keep_their_proportional_slack(self) -> None:
        """The cap only binds where 20% is a large absolute number - a
        weekly bill that drifts a day is still weekly."""
        assert _frequency_for(7) == "weekly"
        assert _frequency_for(8) == "weekly"
        assert _frequency_for(31) == "monthly"
        assert _frequency_for(88) == "quarterly"


class TestRhythmRatio:
    def test_a_steady_cadence_scores_one(self) -> None:
        assert _rhythm_ratio([30, 31, 29], 30) == 1.0

    def test_noise_scores_low(self) -> None:
        """Stewart's actual gaps."""
        assert _rhythm_ratio([2044, 430, 17], 365) < 0.5

    def test_one_skipped_month_still_counts(self) -> None:
        """A real bill that missed a month must not be thrown away."""
        assert _rhythm_ratio([30, 60, 30], 30) >= 0.6

    def test_no_gaps_scores_zero(self) -> None:
        assert _rhythm_ratio([], 30) == 0.0


class TestDetectionEndToEnd:
    @pytest.mark.asyncio
    async def test_a_real_monthly_bill_is_still_found(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _spend(svc, account.id, [date(2026, m, 9) for m in range(1, 6)])

        result = await detect_recurring(async_db_session, owner_user_id=1)

        assert result.detected == 1

    @pytest.mark.asyncio
    async def test_random_visits_are_not_a_subscription(
        self, async_db_session: AsyncSession
    ) -> None:
        """The Stewart's shape, rebuilt: four visits, no rhythm."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        start = date(2019, 8, 26)
        days = [start, start + timedelta(days=2044),
                start + timedelta(days=2474), start + timedelta(days=2491)]
        await _spend(svc, account.id, days, name="STEWART'S SHOPS")

        result = await detect_recurring(async_db_session, owner_user_id=1)

        assert result.detected == 0

    @pytest.mark.asyncio
    async def test_a_genuine_yearly_bill_survives(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _spend(
            svc, account.id,
            [date(2023, 3, 1), date(2024, 3, 2), date(2025, 3, 1)],
            name="ANNUAL DUES",
        )

        result = await detect_recurring(async_db_session, owner_user_id=1)

        assert result.detected == 1

    @pytest.mark.asyncio
    async def test_confidence_reflects_fit_not_just_count(
        self, async_db_session: AsyncSession
    ) -> None:
        """Stewart's scored 90 because confidence was 50 + 10 x occurrences
        - more random visits raised it."""
        from sqlmodel import select

        from app.services.finance.models import FinanceRecurringStream

        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _spend(svc, account.id, [date(2026, m, 9) for m in range(1, 6)])
        await detect_recurring(async_db_session, owner_user_id=1)
        steady = (await async_db_session.exec(select(FinanceRecurringStream))).one()

        assert steady.confidence is not None and steady.confidence >= 85


class TestStreamsThatNoLongerQualify:
    """Tightening the gates has to remove what they now reject.

    A group that fails a gate is skipped - and skipping leaves its
    members' ``recurring_stream_id`` pointing at the old stream, so the
    stream still has members, never orphans, and ``_prune_orphans`` never
    touches it. The junk survives every future scan with its stale
    cadence and its old confidence.
    """

    @pytest.mark.asyncio
    async def test_a_stream_that_fails_the_new_gates_is_retired(
        self, async_db_session: AsyncSession
    ) -> None:
        from sqlmodel import select

        from app.services.finance.models import (
            FinanceRecurringStream,
            FinanceTransaction,
        )

        svc = FinanceService(async_db_session)
        account = await _account(svc)
        # A clean monthly run, detected the normal way.
        txns = await _spend(
            svc, account.id, [date(2026, m, 9) for m in range(1, 6)], name="ACME"
        )
        assert (await detect_recurring(async_db_session, owner_user_id=1)).detected == 1
        stream = (await async_db_session.exec(select(FinanceRecurringStream))).one()

        # Now the rhythm breaks: the remaining history is noise.
        for txn in txns[1:]:
            txn.deleted_at = None
            txn.date_ = date(2026, 1, 9) + timedelta(days=900 * txns.index(txn))
            async_db_session.add(txn)
        await async_db_session.flush()

        await detect_recurring(async_db_session, owner_user_id=1)

        live = (
            await async_db_session.exec(
                select(FinanceRecurringStream).where(
                    FinanceRecurringStream.deleted_at.is_(None)
                )
            )
        ).all()
        assert live == [], "a stream that no longer qualifies must not survive"
        orphaned = (
            await async_db_session.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.recurring_stream_id == stream.id
                )
            )
        ).all()
        assert orphaned == [], "members must be unlinked so the stream can orphan"


class TestDeadStreams:
    """A bill that stopped is not a bill.

    These pass every shape test - CAPITAL ONE AUTO CARPAY really was
    monthly, and so were Wix, AES, TJX and Synchrony. They ended in 2019.
    Nothing about their cadence says so, only their silence since.

    The window has to scale with the cadence: 12 months of quiet kills a
    monthly bill, but an annual one is legitimately quiet for 11.
    """

    @pytest.mark.asyncio
    async def test_a_monthly_bill_that_stopped_years_ago_is_dropped(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _spend(
            svc, account.id,
            [date(2019, m, 2) for m in (7, 8, 9, 10, 11)],
            name="CAPITAL ONE AUTO CARPAY",
        )

        result = await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 2)
        )

        assert result.detected == 0

    @pytest.mark.asyncio
    async def test_a_monthly_bill_still_running_survives(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _spend(
            svc, account.id, [date(2026, m, 9) for m in range(3, 8)], name="ACME"
        )

        result = await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 2)
        )

        assert result.detected == 1

    @pytest.mark.asyncio
    async def test_an_annual_bill_is_allowed_a_long_silence(
        self, async_db_session: AsyncSession
    ) -> None:
        """11 months since the last charge is NORMAL for a yearly bill -
        a flat 12-month rule would delete every one of them."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _spend(
            svc, account.id,
            [date(2023, 9, 1), date(2024, 9, 1), date(2025, 9, 1)],
            name="ANNUAL DUES",
        )

        result = await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 2)
        )

        assert result.detected == 1


class TestChurnSelfHeals:
    """Under rebuild there is nothing to revive - and nothing to protect.

    The old regime needed a watermark so a pass running different rules
    could not resurrect a retired row from its own stale evidence. Rebuild
    makes the whole question moot: even if some pass DOES regenerate a
    stale proposal (a backfill run with an old ``today``, an old code
    version), the very next current-dated pass purges it again, because a
    proposal only exists while a pass justifies it. Convergence is a
    property of the regime, not of per-row bookkeeping.
    """

    @pytest.mark.asyncio
    async def test_a_stale_proposal_resurrected_by_a_backdated_pass_dies_again(
        self, async_db_session: AsyncSession
    ) -> None:
        from sqlmodel import select

        from app.services.finance.models import FinanceRecurringStream

        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _spend(
            svc, account.id, [date(2019, m, 2) for m in (7, 8, 9, 10, 11)],
            name="CAPITAL ONE AUTO CARPAY",
        )
        # A pass reading the old rows as if current (old code, a backfill)
        # legitimately proposes the stream.
        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2019, 12, 1)
        )
        # The next real-dated pass removes it - no watermark required.
        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 3)
        )

        rows = (
            await async_db_session.exec(select(FinanceRecurringStream))
        ).all()
        assert rows == []


class TestTrivialAmounts:
    """A perfect rhythm on trivial money is still noise.

    A savings account paid a $0.31 dividend 54 months running - flawless
    cadence, fixed amount, 100% confidence by every other measure. It is
    not a bill and not income; it is a rounding error with a heartbeat.
    """

    @pytest.mark.asyncio
    async def test_a_rounding_error_is_not_a_stream(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _spend(
            svc, account.id, [date(2026, m, 28) for m in range(1, 7)],
            cents=-31, name="Deposit Dividend 0.020%",
        )

        result = await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 2)
        )

        assert result.detected == 0

    @pytest.mark.asyncio
    async def test_a_small_but_real_subscription_survives(
        self, async_db_session: AsyncSession
    ) -> None:
        """The floor has to sit below a real cheap subscription - $5.41
        CVS ExtraCare is a bill somebody chose to pay."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _spend(
            svc, account.id, [date(2026, m, 9) for m in range(1, 7)],
            cents=-541, name="CVS EXTRACAREPLUS",
        )

        result = await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 2)
        )

        assert result.detected == 1


class TestInflowsOnLiabilityAccounts:
    """Money arriving on a credit card is a PAYMENT, not income.

    A credit on a liability account reduces what you owe - it came from
    another account of yours. Structurally it can never be household
    income, and that is knowable without finding the matching outflow
    (which, on real data, was not even imported: 81 AMEX credits and 33
    Citi credits with no counterpart anywhere).

    They still belong on the card's own register. What they must not
    become is a recurring INCOME stream the forecast counts.
    """

    @pytest.mark.asyncio
    async def test_card_payments_are_not_income_streams(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        card = await svc.create_manual_account(
            name="AMEX", account_type="credit_card",
            classification="liability", owner_user_id=1,
        )
        await _spend(
            svc, card.id, [date(2026, m, 11) for m in range(1, 7)],
            cents=157_527, name="AUTOPAY PAYMENT - THANK YOU",
        )

        result = await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 2)
        )

        assert result.detected == 0

    @pytest.mark.asyncio
    async def test_a_real_paycheck_on_a_cash_account_still_counts(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        checking = await svc.create_manual_account(
            name="Checking", account_type="checking",
            classification="asset", owner_user_id=1,
        )
        await _spend(
            svc, checking.id, [date(2026, m, 8) for m in range(1, 7)],
            cents=203_100, name="SSA TREAS 310 SOC SEC",
        )

        result = await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 2)
        )

        assert result.detected == 1

    @pytest.mark.asyncio
    async def test_spending_on_a_card_is_still_detected(
        self, async_db_session: AsyncSession
    ) -> None:
        """Only the INFLOW direction is structural - a subscription
        charged to the card is a normal bill."""
        svc = FinanceService(async_db_session)
        card = await svc.create_manual_account(
            name="AMEX", account_type="credit_card",
            classification="liability", owner_user_id=1,
        )
        await _spend(
            svc, card.id, [date(2026, m, 9) for m in range(1, 7)],
            cents=-1_599, name="NETFLIX.COM",
        )

        result = await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 2)
        )

        assert result.detected == 1
