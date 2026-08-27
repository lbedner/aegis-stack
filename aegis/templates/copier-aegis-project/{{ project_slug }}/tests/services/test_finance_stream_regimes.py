"""The structural contract: one table, two regimes.

THE RECORD  - ``source='user'`` or ``is_user_confirmed``. The user's.
              Detection never reads, writes, revives, or counts them.
PROPOSALS   - everything else. Detection owns them outright: every pass
              REBUILDS them from current evidence and hard-deletes any it
              did not regenerate. A proposal row is never load-bearing.

This replaces the zombie apparatus (soft-delete + watermark + revival +
release + prune) that produced immortal rows: a stream could only die
through a four-link chain, any broken link made it immortal, and revival
had three doors. Under rebuild there is nothing to revive - stale rows
simply are not regenerated.
"""

from datetime import UTC, date, datetime

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection import declare_recurring, detect_recurring
from app.services.finance.models import FinanceRecurringStream
from app.services.finance.service import FinanceService
from tests.services._finance_factories import seed_account as _account
from tests.services._finance_factories import seed_spend_series as _spend
from tests.services._finance_factories import seed_stream

TODAY = date(2026, 8, 3)


async def _rows(db: AsyncSession) -> list[FinanceRecurringStream]:
    return list((await db.exec(select(FinanceRecurringStream))).all())


class TestProposalsAreRebuilt:
    @pytest.mark.asyncio
    async def test_a_stale_proposal_is_hard_deleted_not_soft(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """No debris. A proposal that stops being justified does not linger
        as a soft-deleted ghost holding a unique key - it is GONE."""
        account = await _account(svc)
        txns = await _spend(svc, account.id, [date(2026, m, 9) for m in range(1, 6)])
        await detect_recurring(async_db_session, owner_user_id=1, today=TODAY)
        assert len(await _rows(async_db_session)) == 1

        # The evidence disappears (descriptors re-keyed, txns deleted...).
        for txn in txns:
            txn.deleted_at = datetime.now(UTC).replace(tzinfo=None)
            async_db_session.add(txn)
        await async_db_session.flush()
        await detect_recurring(async_db_session, owner_user_id=1, today=TODAY)

        assert await _rows(async_db_session) == []

    @pytest.mark.asyncio
    async def test_rebuild_is_idempotent(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        await _spend(svc, account.id, [date(2026, m, 9) for m in range(1, 6)])

        for _ in range(3):
            await detect_recurring(async_db_session, owner_user_id=1, today=TODAY)

        rows = await _rows(async_db_session)
        assert len(rows) == 1
        assert rows[0].deleted_at is None

    @pytest.mark.asyncio
    async def test_a_proposal_keeps_its_identity_across_rebuilds(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Same evidence -> same row updated in place, not a delete+insert
        churning ids (the UI holds ids across a reload)."""
        account = await _account(svc)
        await _spend(svc, account.id, [date(2026, m, 9) for m in range(1, 6)])
        await detect_recurring(async_db_session, owner_user_id=1, today=TODAY)
        first = (await _rows(async_db_session))[0].id

        await detect_recurring(async_db_session, owner_user_id=1, today=TODAY)

        assert [s.id for s in await _rows(async_db_session)] == [first]


class TestDismissalsSurvive:
    @pytest.mark.asyncio
    async def test_a_muted_proposal_stays_muted_through_rebuilds(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        await _spend(svc, account.id, [date(2026, m, 9) for m in range(1, 6)])
        await detect_recurring(async_db_session, owner_user_id=1, today=TODAY)
        row = (await _rows(async_db_session))[0]
        row.is_muted = True
        async_db_session.add(row)
        await async_db_session.flush()

        await detect_recurring(async_db_session, owner_user_id=1, today=TODAY)

        rows = await _rows(async_db_session)
        assert len(rows) == 1 and rows[0].is_muted is True

    @pytest.mark.asyncio
    async def test_a_deleted_proposal_does_not_come_back_loud(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """delete on a proposal = dismissal. The rhythm keeps firing, so
        the row is regenerated - but silent, never loud."""
        account = await _account(svc)
        await _spend(svc, account.id, [date(2026, m, 9) for m in range(1, 6)])
        await detect_recurring(async_db_session, owner_user_id=1, today=TODAY)
        row = (await _rows(async_db_session))[0]
        await svc.delete_recurring(row.id, owner_user_id=1)

        await detect_recurring(async_db_session, owner_user_id=1, today=TODAY)

        rows = [s for s in await _rows(async_db_session) if s.deleted_at is None]
        assert all(s.is_muted for s in rows)

    @pytest.mark.asyncio
    async def test_a_dismissal_whose_pattern_died_is_purged(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """A dismissal of something no longer proposed is debris."""
        account = await _account(svc)
        txns = await _spend(svc, account.id, [date(2026, m, 9) for m in range(1, 6)])
        await detect_recurring(async_db_session, owner_user_id=1, today=TODAY)
        row = (await _rows(async_db_session))[0]
        row.is_muted = True
        async_db_session.add(row)
        for txn in txns:
            txn.deleted_at = datetime.now(UTC).replace(tzinfo=None)
            async_db_session.add(txn)
        await async_db_session.flush()

        await detect_recurring(async_db_session, owner_user_id=1, today=TODAY)

        assert await _rows(async_db_session) == []


class TestTheRecordIsUntouchable:
    @pytest.mark.asyncio
    async def test_a_confirmed_row_survives_any_rebuild(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Even orphaned, even dead-quiet since 2020 - protection has no
        expiry, and rebuild only sweeps PROPOSALS."""
        account = await _account(svc)
        stream = await seed_stream(
            svc,
            name="Old Payroll",
            direction="inflow",
            frequency="biweekly",
            expected_amount=13_463,
            next_expected_date=date(2020, 4, 3),
            account_id=account.id,
        )

        for _ in range(2):
            await detect_recurring(async_db_session, owner_user_id=1, today=TODAY)

        live = [s for s in await _rows(async_db_session) if s.deleted_at is None]
        assert [s.id for s in live] == [stream.id]
        assert live[0].name == "Old Payroll"

    @pytest.mark.asyncio
    async def test_confirming_a_proposal_moves_it_across_the_line(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Confirm is THE door: the row flips regimes in place, keeps its
        id, and the next rebuild neither deletes nor duplicates it."""
        account = await _account(svc)
        await _spend(svc, account.id, [date(2026, m, 9) for m in range(1, 6)])
        await detect_recurring(async_db_session, owner_user_id=1, today=TODAY)
        row = (await _rows(async_db_session))[0]
        row.is_user_confirmed = True
        async_db_session.add(row)
        await async_db_session.flush()

        await detect_recurring(async_db_session, owner_user_id=1, today=TODAY)

        rows = await _rows(async_db_session)
        assert [s.id for s in rows] == [row.id]
        assert rows[0].is_user_confirmed is True

    @pytest.mark.asyncio
    async def test_declared_bills_are_record_not_proposal(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        txns = await _spend(
            svc, account.id, [date(2026, m, 3) for m in range(1, 5)], name="GYM"
        )
        await declare_recurring(async_db_session, [t.id for t in txns], owner_user_id=1)

        await detect_recurring(async_db_session, owner_user_id=1, today=TODAY)

        live = [s for s in await _rows(async_db_session) if s.deleted_at is None]
        assert len(live) == 1 and live[0].is_user_confirmed


class TestOnlyTheRecordCounts:
    """Money math reads the record, never proposals.

    ``is_commitment`` used to let an unconfirmed detector guess into the
    forecast, the monthly-cost headline, and the missed-payment nag if it
    looked subscription-ish - which is how "$23,575 fixed this month from
    97 detected bills" described rows the user never touched. A proposal
    now counts for NOTHING until confirmed. Confirm is the one door.
    """

    @pytest.mark.asyncio
    async def test_a_proposal_never_projects(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        await _spend(svc, account.id, [date(2026, m, 9) for m in range(1, 8)])
        await detect_recurring(async_db_session, owner_user_id=1, today=TODAY)

        result = await svc.project_balances(owner_user_id=1, days=90, today=TODAY)

        assert result.points == []

    @pytest.mark.asyncio
    async def test_a_proposal_costs_nothing_in_the_rollup(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains.detection import commitment_rollup

        account = await _account(svc)
        await _spend(svc, account.id, [date(2026, m, 9) for m in range(1, 8)])
        await detect_recurring(async_db_session, owner_user_id=1, today=TODAY)
        streams = list(await _rows(async_db_session))

        assert commitment_rollup(streams)["monthly_total"] == 0

    @pytest.mark.asyncio
    async def test_confirming_makes_it_count(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains.detection import commitment_rollup

        account = await _account(svc)
        await _spend(svc, account.id, [date(2026, m, 9) for m in range(1, 8)])
        await detect_recurring(async_db_session, owner_user_id=1, today=TODAY)
        row = (await _rows(async_db_session))[0]
        row.is_user_confirmed = True
        async_db_session.add(row)
        await async_db_session.flush()

        projected = await svc.project_balances(owner_user_id=1, days=90, today=TODAY)
        rollup = commitment_rollup(list(await _rows(async_db_session)))

        assert projected.points != []
        assert rollup["monthly_total"] > 0
