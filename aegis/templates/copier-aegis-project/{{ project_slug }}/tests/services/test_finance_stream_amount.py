"""What a bill costs is what it costs NOW.

``finance_recurring_stream.average_amount`` is the number every surface
shows for a bill: Bills & Income, the forecast, the budget rollup and
Illiana all read ``expected_amount or average_amount``, and only seven of
this ledger's sixty-three streams have an ``expected_amount``. So for the
other fifty-six, ``average_amount`` IS the bill's amount.

It was wrong in two compounding ways, and neither could be seen from the
UI - a stale number looks exactly like a fresh one.

1. It was the median over the stream's ENTIRE history. Netflix has 87
   payments going back seven years, so the median sat at $21.61 while the
   last charge was $29.18. Optimum showed $119.99 against $146.18. Apple
   showed $2.99 against $4.31. Every bill that has ever been price-hiked
   was quoted low, and the forecast built on those numbers was low with
   it. The same all-history read fed ``amount_is_variable``, so a fixed
   subscription that went up once was marked "variable" forever.

2. It was written only by the nightly detector, and the detector
   deliberately skips user-confirmed streams (``_curated_members``: a
   bill you settled must not be silently regrouped). Forty-nine of the
   fifty-six derived streams here are confirmed, so their amount froze on
   the day they were confirmed and nothing has touched it since.
   ``attach_transaction_to_stream`` is the ONLY thing that changes a
   confirmed bill's membership, and it updated ``last_amount``,
   ``last_date``, ``occurrence_count`` and ``next_expected_date`` - every
   fact except the one the UI actually shows.
"""

from datetime import date, timedelta
import statistics
from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection.recurring.cadence import amount_profile
from app.services.finance.models import FinanceTransaction
from app.services.finance.service import FinanceService
from app.services.finance.utils import current_date, utcnow
from tests.services._finance_factories import declare_bill, seed_stream, seed_txn
from tests.services._finance_factories import seed_account as _account

TODAY = date(2026, 9, 12)


def _paid(day: date, cents: int, **overrides: Any) -> FinanceTransaction:
    """One unsaved member row - ``amount_profile`` is pure, so nothing
    here needs a database."""
    return FinanceTransaction(
        account_id=1, source="manual", date_=day, amount=-cents, **overrides
    )


def _series(count: int, cents: int, *, ending: date, every: int = 30):
    """``count`` payments of ``cents`` every ``every`` days, last one on
    ``ending`` - the shape of a subscription at one price."""
    return [
        _paid(ending - timedelta(days=every * i), cents)
        for i in range(count - 1, -1, -1)
    ]


class TestTheAmountIsWhatItCostsNow:
    def test_a_price_rise_moves_the_amount(self) -> None:
        """The Netflix shape: four years at one price, one year at
        another. The all-history median answers a question nobody asked
        - what this bill USED to cost."""
        history = _series(48, 999, ending=TODAY - timedelta(days=395)) + _series(
            12, 2918, ending=TODAY
        )

        amount, _ = amount_profile(history, today=TODAY)

        assert amount == 2918
        assert statistics.median([abs(t.amount) for t in history]) == 999

    def test_a_price_rise_does_not_make_a_fixed_bill_variable(self) -> None:
        """Every recent charge is identical; the spread is entirely
        historical. Marking this "variable" costs the stream its
        subscription flag and loosens every amount check downstream."""
        history = _series(48, 999, ending=TODAY - timedelta(days=395)) + _series(
            12, 2918, ending=TODAY
        )

        _, variable = amount_profile(history, today=TODAY)

        assert variable is False

    def test_a_bill_that_really_does_vary_is_still_variable(self) -> None:
        """The window narrows what is looked at, not what counts as
        variable - a utility bill must not come out "fixed"."""
        history = [
            _paid(TODAY - timedelta(days=30 * i), cents)
            for i, cents in enumerate([11999, 8450, 15200, 9100, 13700, 7800])
        ]

        _, variable = amount_profile(history, today=TODAY)

        assert variable is True

    def test_an_annual_bill_falls_back_to_its_last_few_occurrences(self) -> None:
        """A year's window holds at most one annual charge, and the
        median of one number is that number - one odd renewal would
        become the bill. Below three samples the window gives way to the
        last three occurrences, however long they took."""
        history = [
            _paid(date(year, 3, 1), cents)
            for year, cents in zip(
                range(2021, 2027), [1000, 1100, 1200, 1300, 1400, 1500]
            )
        ]

        amount, _ = amount_profile(history, today=TODAY)

        assert amount == 1400

    def test_a_stream_with_no_members_has_no_amount(self) -> None:
        """``statistics.median([])`` raises; a purged stream must not
        take the nightly pass down with it."""
        assert amount_profile([], today=TODAY) == (0, False)


class TestAConfirmedBillsAmountKeepsUp:
    @pytest.mark.asyncio
    async def test_attaching_payments_refreshes_what_the_bill_costs(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The detector will never look at this stream again. If the
        attach does not recompute, the bill quotes its 2024 price for
        the rest of its life."""
        today = current_date()
        account = await _account(svc)
        stream, _ = await declare_bill(
            svc,
            async_db_session,
            account.id,
            "STREAMING CO",
            [today - timedelta(days=d) for d in (900, 870, 840, 810)],
            cents=-999,
        )
        assert stream.average_amount == 999

        for days_ago in (70, 40, 10):
            txn = await seed_txn(
                svc,
                account.id,
                -2918,
                today - timedelta(days=days_ago),
                name="STREAMING CO",
            )
            await svc.attach_transaction_to_stream(txn.id, stream.id, owner_user_id=1)

        await async_db_session.refresh(stream)
        assert stream.average_amount == 2918


class TestADeletedRowDoesNotSetThePrice:
    def test_deleted_members_are_ignored(self) -> None:
        """Detection pre-filters them; the attach path and the recompute
        read a stream's members whole, so the rule lives in one place."""
        history = _series(6, 999, ending=TODAY)
        history.append(_paid(TODAY, 50_000, deleted_at=utcnow()))

        assert amount_profile(history, today=TODAY) == (999, False)


class TestTheRecomputeUnsticksTheFrozenOnes:
    """The attach fix only helps a bill from its next payment onward. The
    ones already frozen need to be re-read once, and the same verb is
    right again after a restore or a bulk re-match - so a recompute,
    answering to the member transactions, not a one-off backfill."""

    @pytest.mark.asyncio
    async def test_it_re_reads_a_frozen_bill_from_its_members(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        today = current_date()
        account = await _account(svc)
        stream, _ = await declare_bill(
            svc,
            async_db_session,
            account.id,
            "STREAMING CO",
            [today - timedelta(days=d) for d in (900, 870, 840, 810)],
            cents=-999,
        )
        # The frozen state: members arrived without anything re-reading
        # the amount, which is exactly what the detector's skip produces.
        for days_ago in (70, 40, 10):
            txn = await seed_txn(
                svc, account.id, -2918, today - timedelta(days=days_ago)
            )
            txn.recurring_stream_id = stream.id
            async_db_session.add(txn)
        await async_db_session.flush()
        assert stream.average_amount == 999

        counts = await svc.recompute_stream_amounts(owner_user_id=1)

        await async_db_session.refresh(stream)
        assert stream.average_amount == 2918
        assert counts["changed"] == 1

    @pytest.mark.asyncio
    async def test_running_it_again_changes_nothing(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Idempotent, or it is a migration pretending to be a command.

        Stated as "a stream already settled is left alone" rather than
        by invoking the command twice: two runs in one test issue the
        same SELECT twice, which the N+1 gate reads as a repeated
        statement - correctly, since it cannot know the second run is
        the assertion. The claim is the same and the setup is honest,
        because ``declare_recurring`` writes the amount through the very
        profile the recompute re-reads.
        """
        account = await _account(svc)
        today = current_date()
        stream, _ = await declare_bill(
            svc,
            async_db_session,
            account.id,
            "STREAMING CO",
            [today - timedelta(days=d) for d in (90, 60, 30)],
            cents=-999,
        )
        assert stream.average_amount == 999

        counts = await svc.recompute_stream_amounts(owner_user_id=1)

        assert counts["changed"] == 0
        assert counts["released"] == 0

    @pytest.mark.asyncio
    async def test_a_bill_with_no_payments_keeps_what_it_was_told(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """A hand-entered bill that has never been matched has no
        evidence - and no evidence must not read as "it costs nothing"."""
        stream = await seed_stream(
            svc,
            name="RENT",
            expected_amount=250_000,
            next_expected_date=current_date() + timedelta(days=10),
        )

        await svc.recompute_stream_amounts(owner_user_id=1)

        await async_db_session.refresh(stream)
        assert stream.average_amount == 250_000


class TestTheRecomputeRepairsMembershipFirst:
    """The amount is read off the membership, so a stream holding rows
    that were never payments cannot be fixed by re-reading alone. The
    repair drops the amount band that the live attach path uses: it is
    re-reading streams whose amount is KNOWN to be wrong, so banding on
    that figure would throw away real payments to protect a number
    nobody trusts (American Express lost 67 of its 83 payments that
    way). One-per-period holds regardless - a monthly bill is paid once
    a month whatever it costs."""

    @pytest.mark.asyncio
    async def test_it_releases_the_rows_that_were_never_payments(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The Citi shape, already in the ledger: three lines a
        statement, so the median describes none of them."""
        today = current_date()
        account = await _account(svc)
        stream, _ = await declare_bill(
            svc,
            async_db_session,
            account.id,
            "CARD CO",
            [today - timedelta(days=d) for d in (90, 60, 30)],
            cents=-11_790,
        )
        extras = []
        for days_ago in (90, 60, 30):
            row = await seed_txn(
                svc, account.id, -2_924, today - timedelta(days=days_ago)
            )
            row.recurring_stream_id = stream.id
            async_db_session.add(row)
            extras.append(row)
        await async_db_session.flush()

        counts = await svc.recompute_stream_amounts(owner_user_id=1)

        assert counts["released"] == 3
        # Read the membership back in ONE query: refreshing rows one by
        # one re-loads a column per object, which is an N+1 and which
        # the queryspy gate is right to fail on.
        from app.services.finance.domains.planning.recurring import queries

        claimed = {
            t.id for t in await queries.stream_members(async_db_session, stream.id)
        }
        assert claimed.isdisjoint({row.id for row in extras})
        await async_db_session.refresh(stream)
        assert stream.average_amount == 11_790
