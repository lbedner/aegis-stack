"""Attaching a stray transaction to the bill it paid.

The matcher unites bills and transactions automatically when the payee
key lines up - but a changed descriptor, a hand-entered bill, or an
excluded row breaks the link, and the bill nags "hasn't been paid"
about money that visibly left (12 overdue-but-paid bills, confirmed
live). Attach is the reconciliation verb: consume the occurrence AND
teach the payee key, so future months match on their own - the half
Quicken's "mark as paid" never had.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.service import FinanceService
from tests.services._finance_factories import seed_account as _account
from tests.services._finance_factories import seed_stream


async def _bill(svc, account, **overrides):
    defaults = dict(
        name="World Anvil",
        expected_amount=1_500,
        next_expected_date=date(2026, 7, 30),
        account_id=account.id,
    )
    defaults.update(overrides)
    return await seed_stream(svc, **defaults)


async def _payment(
    svc, account, *, day=date(2026, 8, 2), cents=-1_500, name="WORLDANVIL.COM 88291"
):
    return await svc.create_transaction(
        account_id=account.id,
        amount=cents,
        txn_date=day,
        owner_user_id=1,
        name=name,
    )


class TestAttach:
    @pytest.mark.asyncio
    async def test_it_consumes_the_occurrence(
        self, async_db_session: AsyncSession
    ) -> None:
        """Membership set, due date stepped from the PAYMENT's date (the
        same rule the automatic matcher follows), occurrence counted."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        bill = await _bill(svc, account)
        payment = await _payment(svc, account)

        updated = await svc.attach_transaction_to_stream(
            payment.id, bill.id, owner_user_id=1
        )

        await async_db_session.refresh(payment)
        assert payment.recurring_stream_id == bill.id
        assert updated.next_expected_date == date(2026, 9, 2)
        assert updated.last_date == date(2026, 8, 2)
        assert updated.occurrence_count == 1

    @pytest.mark.asyncio
    async def test_it_teaches_the_bill_the_payees_key(
        self, async_db_session: AsyncSession
    ) -> None:
        """The half that ends the treadmill: the bill adopts the
        transaction's merchant, so NEXT month's charge matches without
        anyone doing anything."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        merchant = await svc.create_merchant("World Anvil", owner_user_id=1)
        bill = await _bill(svc, account)
        payment = await _payment(svc, account)
        payment.merchant_id = merchant.id
        async_db_session.add(payment)
        await async_db_session.flush()

        updated = await svc.attach_transaction_to_stream(
            payment.id, bill.id, owner_user_id=1
        )

        assert updated.merchant_id == merchant.id

    @pytest.mark.asyncio
    async def test_it_teaches_the_transaction_when_the_bill_knows_more(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        merchant = await svc.create_merchant("World Anvil", owner_user_id=1)
        bill = await _bill(svc, account)
        bill.merchant_id = merchant.id
        async_db_session.add(bill)
        payment = await _payment(svc, account)

        await svc.attach_transaction_to_stream(payment.id, bill.id, owner_user_id=1)

        await async_db_session.refresh(payment)
        assert payment.merchant_id == merchant.id

    @pytest.mark.asyncio
    async def test_it_backfills_the_payees_history(
        self, async_db_session: AsyncSession
    ) -> None:
        """Attaching one payment claims the payee's OTHER unclaimed rows
        too. Teaching the key only helps future months; without the
        backfill, last quarter's payments still read as unplanned
        spending and the "Everything else" figure double-counts the bill
        (confirmed live: a nursing-home bill counted once in BILLS and
        again in the observed run rate)."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        bill = await _bill(svc, account)
        payee = await svc.create_merchant("World Anvil", owner_user_id=1)
        history = []
        for month, cents in ((5, -1_500), (6, -1_800), (7, -1_500)):
            row = await _payment(svc, account, day=date(2026, month, 2), cents=cents)
            row.merchant_id = payee.id
            async_db_session.add(row)
            history.append(row)
        await async_db_session.flush()
        latest = history[-1]

        await svc.attach_transaction_to_stream(latest.id, bill.id, owner_user_id=1)

        for row in history:
            await async_db_session.refresh(row)
            assert row.recurring_stream_id == bill.id

    @pytest.mark.asyncio
    async def test_backfill_never_steals_claimed_rows(
        self, async_db_session: AsyncSession
    ) -> None:
        """A row another live bill already claims stays claimed - the
        backfill sweeps strays, it does not re-litigate memberships."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        bill = await _bill(svc, account)
        other = await _bill(svc, account, name="Other bill")
        payee = await svc.create_merchant("World Anvil", owner_user_id=1)
        claimed = await _payment(svc, account, day=date(2026, 6, 2))
        claimed.merchant_id = payee.id
        claimed.recurring_stream_id = other.id
        stray = await _payment(svc, account, day=date(2026, 7, 2))
        stray.merchant_id = payee.id
        async_db_session.add(claimed)
        async_db_session.add(stray)
        await async_db_session.flush()
        latest = await _payment(svc, account, day=date(2026, 8, 2))
        latest.merchant_id = payee.id
        async_db_session.add(latest)
        await async_db_session.flush()

        await svc.attach_transaction_to_stream(latest.id, bill.id, owner_user_id=1)

        await async_db_session.refresh(claimed)
        await async_db_session.refresh(stray)
        assert claimed.recurring_stream_id == other.id
        assert stray.recurring_stream_id == bill.id

    @pytest.mark.asyncio
    async def test_an_older_payment_never_moves_the_date_backward(
        self, async_db_session: AsyncSession
    ) -> None:
        """Attaching June's charge for the record must not re-arm July's
        nag by dragging next_expected_date into the past."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        bill = await _bill(svc, account, next_expected_date=date(2026, 8, 30))
        payment = await _payment(svc, account, day=date(2026, 6, 2))

        updated = await svc.attach_transaction_to_stream(
            payment.id, bill.id, owner_user_id=1
        )

        assert updated.next_expected_date == date(2026, 8, 30)

    @pytest.mark.asyncio
    async def test_a_once_bill_completes_instead_of_stepping(
        self, async_db_session: AsyncSession
    ) -> None:
        """ "Pay someone back" has no next occurrence; its payment
        arriving is the end of it, not a reschedule."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        bill = await _bill(
            svc, account, frequency="once", next_expected_date=date(2026, 8, 1)
        )
        payment = await _payment(svc, account)

        updated = await svc.attach_transaction_to_stream(
            payment.id, bill.id, owner_user_id=1
        )

        assert updated.next_expected_date is None

    @pytest.mark.asyncio
    async def test_wrong_owner_touches_nothing(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        bill = await _bill(svc, account)
        payment = await _payment(svc, account)

        assert (
            await svc.attach_transaction_to_stream(
                payment.id, bill.id, owner_user_id=99
            )
            is None
        )


class TestMatchCandidates:
    @pytest.mark.asyncio
    async def test_candidates_look_like_the_bill(
        self, async_db_session: AsyncSession
    ) -> None:
        """Same direction, unclaimed, amount in the neighborhood, recent
        first - the shortlist a human would scan for."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        bill = await _bill(svc, account)
        lookalike = await _payment(svc, account, day=date(2026, 8, 2), cents=-1_500)
        await _payment(
            svc, account, day=date(2026, 8, 3), cents=-90_000, name="MORTGAGE"
        )
        inflow = await svc.create_transaction(
            account_id=account.id,
            amount=1_500,
            txn_date=date(2026, 8, 2),
            owner_user_id=1,
            name="REFUND",
        )

        rows = await svc.recurring_match_candidates(bill.id, owner_user_id=1)

        ids = [t.id for t in rows]
        assert lookalike.id in ids
        assert inflow.id not in ids
        assert all(t.amount < 0 for t in rows)

    @pytest.mark.asyncio
    async def test_already_claimed_rows_stay_out(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        bill = await _bill(svc, account)
        other = await _bill(svc, account, name="Other")
        payment = await _payment(svc, account)
        await svc.attach_transaction_to_stream(payment.id, other.id, owner_user_id=1)

        rows = await svc.recurring_match_candidates(bill.id, owner_user_id=1)

        assert payment.id not in [t.id for t in rows]

    @pytest.mark.asyncio
    async def test_the_likeliest_candidate_sorts_first(
        self, async_db_session: AsyncSession
    ) -> None:
        """A $7.57 bill's band admits every coffee in the register; the
        REAL payment (exact amount, dated near the due date) must not
        drown under twenty newer lookalikes (confirmed live: the World
        Anvil payment sat below a page of Targets)."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        bill = await _bill(
            svc, account, expected_amount=757, next_expected_date=date(2026, 7, 30)
        )
        real = await _payment(
            svc,
            account,
            day=date(2026, 7, 27),
            cents=-757,
            name="ROSE OF ETERNITY - DEVELOPMENT",
        )
        for day in (date(2026, 8, 7), date(2026, 8, 8)):
            await _payment(svc, account, day=day, cents=-756, name="TARGET")

        rows = await svc.recurring_match_candidates(bill.id, owner_user_id=1)

        assert rows[0].id == real.id


class TestDeleteReleasesMembers:
    """Deleting a stream must free its transactions.

    It never did: soft-delete kept every member's ``recurring_stream_id``
    pointing at the corpse, leaving them invisible to Match (claimed),
    invisible to re-detection (pinned), and the user's CONFIRMED twin
    starving forever (confirmed live: 366 transactions zombie-claimed by
    20 dead streams; the Fidelity bill sat overdue while every $347.48
    payment belonged to a stream deleted on Aug 5)."""

    @pytest.mark.asyncio
    async def test_members_are_freed_on_delete(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        bill = await _bill(svc, account)
        payment = await _payment(svc, account)
        await svc.attach_transaction_to_stream(payment.id, bill.id, owner_user_id=1)

        assert await svc.delete_recurring(bill.id, owner_user_id=1) is True

        await async_db_session.refresh(payment)
        assert payment.recurring_stream_id is None


class TestNameTakesPrecedence:
    @pytest.mark.asyncio
    async def test_a_payee_match_outranks_a_closer_amount(
        self, async_db_session: AsyncSession
    ) -> None:
        """ "Fidelity" in the candidate beats a stranger a dollar nearer:
        the list ranked purely on figures, so Etsy and DoorDash from last
        year outranked rows that carry the bill's own name."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        merchant = await svc.create_merchant("Fidelity", owner_user_id=1)
        bill = await _bill(
            svc,
            account,
            name="Fidelity",
            expected_amount=34_748,
            next_expected_date=date(2026, 8, 1),
        )
        bill.merchant_id = merchant.id
        async_db_session.add(bill)
        stranger = await _payment(
            svc, account, day=date(2026, 8, 1), cents=-34_748, name="ETSY PURCHASE"
        )
        named = await _payment(
            svc,
            account,
            day=date(2026, 8, 3),
            cents=-34_700,
            name="FIDELITY CONTRIBUTION",
        )
        await async_db_session.flush()

        rows = await svc.recurring_match_candidates(bill.id, owner_user_id=1)

        assert rows[0].id == named.id
        # When rows carry the bill's own name, strangers are noise and
        # stay out entirely - "it's so obviously Fidelity and not AT&T".
        assert stranger.id not in [t.id for t in rows]

    @pytest.mark.asyncio
    async def test_a_dead_streams_claim_does_not_hide_a_candidate(
        self, async_db_session: AsyncSession
    ) -> None:
        """A dismissed detector guess keeps claiming its pattern's rows
        (by design - that is how a dismissal stays silent), but a human
        reconciling a CONFIRMED bill outranks a dead proposal: the row
        must appear, and attaching it re-parents the claim."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        bill = await _bill(svc, account, name="Fidelity", expected_amount=34_748)
        twin = await _bill(svc, account, name="Fidelity twin", expected_amount=34_748)
        payment = await _payment(
            svc, account, cents=-34_748, name="FIDELITY CONTRIBUTION"
        )
        await svc.attach_transaction_to_stream(payment.id, twin.id, owner_user_id=1)
        await svc.delete_recurring(twin.id, owner_user_id=1)
        # simulate detection re-claiming into the corpse
        payment.recurring_stream_id = twin.id
        async_db_session.add(payment)
        await async_db_session.flush()

        rows = await svc.recurring_match_candidates(bill.id, owner_user_id=1)

        assert payment.id in [t.id for t in rows]

        updated = await svc.attach_transaction_to_stream(
            payment.id, bill.id, owner_user_id=1
        )
        await async_db_session.refresh(payment)
        assert payment.recurring_stream_id == bill.id
        assert updated is not None

    @pytest.mark.asyncio
    async def test_strangers_still_show_when_nothing_wears_the_name(
        self, async_db_session: AsyncSession
    ) -> None:
        """The amount shortlist is the whole value when the payment came
        through under an unrecognizable descriptor."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        bill = await _bill(
            svc,
            account,
            name="World Anvil",
            expected_amount=757,
            next_expected_date=date(2026, 7, 30),
        )
        renamed = await _payment(
            svc,
            account,
            day=date(2026, 7, 27),
            cents=-757,
            name="ROSE OF ETERNITY - DEV",
        )

        rows = await svc.recurring_match_candidates(bill.id, owner_user_id=1)

        assert renamed.id in [t.id for t in rows]

    @pytest.mark.asyncio
    async def test_history_stays_out_of_a_reconciliation(
        self, async_db_session: AsyncSession
    ) -> None:
        """The dialog answers "which payment was THIS due date" - last
        year's identical charges are not answers to that question, and
        six of them crowded out everything else (confirmed live)."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        merchant = await svc.create_merchant("Fidelity", owner_user_id=1)
        bill = await _bill(
            svc,
            account,
            name="Fidelity",
            expected_amount=34_748,
            next_expected_date=date(2026, 8, 1),
        )
        bill.merchant_id = merchant.id
        async_db_session.add(bill)
        current = await _payment(
            svc,
            account,
            day=date(2026, 8, 3),
            cents=-34_748,
            name="FIDELITY CONTRIBUTION",
        )
        ancient = await _payment(
            svc,
            account,
            day=date(2025, 9, 2),
            cents=-34_748,
            name="FIDELITY CONTRIBUTION",
        )
        await async_db_session.flush()

        rows = await svc.recurring_match_candidates(bill.id, owner_user_id=1)

        ids = [t.id for t in rows]
        assert current.id in ids
        assert ancient.id not in ids
