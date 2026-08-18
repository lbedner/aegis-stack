"""Tests for the finance demo dataset seeder.

The seeder exists to make a fresh install look like a working app: accounts,
months of believable activity, and a net-worth curve. These tests pin the
properties that promise buys - the account set, a populated ledger, a curve
that actually moves, and the idempotence that makes re-running safe.
"""

from datetime import date, timedelta

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import (
    FinanceAccount,
    FinanceImportBatch,
    FinanceNetWorthSnapshot,
    FinanceRecurringStream,
    FinanceTransaction,
    FinanceTransactionSplit,
    FinanceTransfer,
)
from app.services.finance.seeds import demo_seed
from app.services.finance.service import FinanceService

OWNER = 1


async def _accounts(session: AsyncSession) -> list[FinanceAccount]:
    query = select(FinanceAccount).where(FinanceAccount.deleted_at.is_(None))
    return list((await session.exec(query)).all())


async def _transactions(session: AsyncSession) -> list[FinanceTransaction]:
    return list((await session.exec(select(FinanceTransaction))).all())


class TestLedgerPlan:
    """The ledger plan is pure, so determinism is testable without a DB."""

    def test_same_inputs_produce_an_identical_ledger(self) -> None:
        anchor = date(2026, 7, 1)
        first = demo_seed.build_demo_ledger(anchor=anchor, months=8)
        second = demo_seed.build_demo_ledger(anchor=anchor, months=8)
        assert first == second
        assert first, "expected a non-empty ledger"

    def test_ledger_spans_the_requested_window(self) -> None:
        anchor = date(2026, 7, 1)
        months = 8
        ledger = demo_seed.build_demo_ledger(anchor=anchor, months=months)
        earliest = min(entry.txn_date for entry in ledger)
        assert earliest <= anchor - timedelta(days=30 * (months - 1))
        assert max(entry.txn_date for entry in ledger) <= anchor

    def test_ledger_carries_recurring_payees(self) -> None:
        """Salary, housing, and subscriptions repeat so stream detection has
        something to find."""
        ledger = demo_seed.build_demo_ledger(anchor=date(2026, 7, 1), months=8)
        counts: dict[str, int] = {}
        for entry in ledger:
            counts[entry.name] = counts.get(entry.name, 0) + 1
        recurring = [name for name, count in counts.items() if count >= 6]
        assert len(recurring) >= 4, f"too few recurring payees: {counts}"


class TestSeedDemo:
    @pytest.mark.asyncio
    async def test_creates_the_expected_account_set(
        self, async_db_session: AsyncSession
    ) -> None:
        result = await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER)
        await async_db_session.commit()

        accounts = await _accounts(async_db_session)
        assert {a.name for a in accounts} == set(demo_seed.DEMO_ACCOUNT_NAMES)
        assert 4 <= len(accounts) <= 6
        assert result.accounts == len(accounts)
        # Every type the dashboard renders differently is represented.
        types = {a.account_type for a in accounts}
        assert {"checking", "savings", "credit_card", "property"} <= types
        assert {a.classification for a in accounts} == {"asset", "liability"}

    @pytest.mark.asyncio
    async def test_creates_a_populated_ledger(
        self, async_db_session: AsyncSession
    ) -> None:
        result = await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER)
        await async_db_session.commit()

        transactions = await _transactions(async_db_session)
        assert result.transactions > 0
        assert len(transactions) == result.transactions
        span_days = (
            max(t.date_ for t in transactions) - min(t.date_ for t in transactions)
        ).days
        assert span_days >= 150, "expected at least ~6 months of history"

    @pytest.mark.asyncio
    async def test_records_splits_and_a_confirmed_transfer(
        self, async_db_session: AsyncSession
    ) -> None:
        await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER)
        await async_db_session.commit()

        splits = (await async_db_session.exec(select(FinanceTransactionSplit))).all()
        assert splits, "expected at least one split transaction"

        transfers = (await async_db_session.exec(select(FinanceTransfer))).all()
        confirmed = [t for t in transfers if t.status == "confirmed"]
        assert confirmed, "expected at least one auto-paired transfer"

    @pytest.mark.asyncio
    async def test_routes_recent_activity_through_the_import_lane(
        self, async_db_session: AsyncSession
    ) -> None:
        """The most recent slice arrives as a file import, so the import
        history surface is populated too."""
        result = await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER)
        await async_db_session.commit()

        batches = (await async_db_session.exec(select(FinanceImportBatch))).all()
        assert batches, "expected an import batch"
        assert sum(b.rows_total for b in batches) > 0
        assert result.imported_rows > 0

    @pytest.mark.asyncio
    async def test_net_worth_snapshots_span_the_window_and_move(
        self, async_db_session: AsyncSession
    ) -> None:
        await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER)
        await async_db_session.commit()

        snapshots = (
            await async_db_session.exec(
                select(FinanceNetWorthSnapshot).order_by(
                    FinanceNetWorthSnapshot.as_of_date
                )
            )
        ).all()
        assert len(snapshots) >= 150, "expected a multi-month net-worth series"
        values = {s.net_worth_amount for s in snapshots}
        assert len(values) > 1, "net worth should curve, not flatline"

    @pytest.mark.asyncio
    async def test_second_run_is_a_noop(self, async_db_session: AsyncSession) -> None:
        await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER)
        await async_db_session.commit()
        before_accounts = len(await _accounts(async_db_session))
        before_txns = len(await _transactions(async_db_session))

        again = await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER)
        await async_db_session.commit()

        assert again.skipped is True
        assert again.transactions == 0
        assert len(await _accounts(async_db_session)) == before_accounts
        assert len(await _transactions(async_db_session)) == before_txns

    @pytest.mark.asyncio
    async def test_reset_reseeds_without_duplicating(
        self, async_db_session: AsyncSession
    ) -> None:
        first = await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER)
        await async_db_session.commit()

        second = await demo_seed.seed_demo(
            async_db_session, owner_user_id=OWNER, reset=True
        )
        await async_db_session.commit()

        assert second.skipped is False
        assert second.accounts == first.accounts
        assert len(await _accounts(async_db_session)) == first.accounts
        assert len(await _transactions(async_db_session)) == second.transactions

    @pytest.mark.asyncio
    async def test_reset_leaves_real_rows_untouched(
        self, async_db_session: AsyncSession
    ) -> None:
        """``--reset`` scopes its deletes to seeded rows, never the user's."""
        service = FinanceService(async_db_session)
        real = await service.create_manual_account(
            owner_user_id=OWNER,
            name="Chase Total Checking",  # same name as a demo account
            account_type="checking",
            classification="asset",
        )
        real_txn = await service.create_transaction(
            owner_user_id=OWNER,
            account_id=real.id,
            amount=-1234,
            txn_date=date(2026, 6, 1),
            name="Whole Foods Market",
        )
        await async_db_session.commit()

        await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER, reset=True)
        await async_db_session.commit()

        survivor = await service.get_account(real.id, owner_user_id=OWNER)
        assert survivor is not None, "reset deleted a real account"
        still_there = (
            await async_db_session.exec(
                select(FinanceTransaction).where(FinanceTransaction.id == real_txn.id)
            )
        ).first()
        assert still_there is not None, "reset deleted a real transaction"

    @pytest.mark.asyncio
    async def test_standalone_mode_seeds_with_a_null_owner(
        self, async_db_session: AsyncSession
    ) -> None:
        result = await demo_seed.seed_demo(async_db_session, owner_user_id=None)
        await async_db_session.commit()

        accounts = await _accounts(async_db_session)
        assert result.accounts == len(accounts)
        assert all(a.owner_user_id is None for a in accounts)

    @pytest.mark.asyncio
    async def test_reported_counts_match_what_is_in_the_database(
        self, async_db_session: AsyncSession
    ) -> None:
        """The CLI prints these numbers, so they have to be the real ones.

        The detectors also run inside the import lane, so counting a
        detector's own return value undercounts everything it already did.
        """
        result = await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER)
        await async_db_session.commit()

        transfers = (await async_db_session.exec(select(FinanceTransfer))).all()
        streams = (await async_db_session.exec(select(FinanceRecurringStream))).all()
        splits = (await async_db_session.exec(select(FinanceTransactionSplit))).all()
        assert result.transfers == len(transfers)
        assert result.recurring == len(streams)
        assert result.splits == len(splits)


class TestForeignAccounts:
    """Seeding into a database that already holds real finance data is the
    one genuinely risky case, so callers can detect it up front."""

    @pytest.mark.asyncio
    async def test_reports_zero_on_an_empty_install(
        self, async_db_session: AsyncSession
    ) -> None:
        count = await demo_seed.count_foreign_accounts(
            async_db_session, owner_user_id=OWNER
        )
        assert count == 0

    @pytest.mark.asyncio
    async def test_seeded_accounts_do_not_count_as_foreign(
        self, async_db_session: AsyncSession
    ) -> None:
        await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER)
        await async_db_session.commit()
        count = await demo_seed.count_foreign_accounts(
            async_db_session, owner_user_id=OWNER
        )
        assert count == 0

    @pytest.mark.asyncio
    async def test_counts_the_users_own_accounts(
        self, async_db_session: AsyncSession
    ) -> None:
        service = FinanceService(async_db_session)
        await service.create_manual_account(
            owner_user_id=OWNER,
            name="Real Checking",
            account_type="checking",
            classification="asset",
        )
        await async_db_session.commit()
        count = await demo_seed.count_foreign_accounts(
            async_db_session, owner_user_id=OWNER
        )
        assert count == 1


class TestClearDemo:
    @pytest.mark.asyncio
    async def test_clear_removes_everything_without_reseeding(
        self, async_db_session: AsyncSession
    ) -> None:
        await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER)
        await async_db_session.commit()

        removed = await demo_seed.clear_demo(async_db_session, owner_user_id=OWNER)
        await async_db_session.commit()

        assert removed == len(demo_seed.DEMO_ACCOUNT_NAMES)
        assert await _accounts(async_db_session) == []
        assert await _transactions(async_db_session) == []
        assert (await async_db_session.exec(select(FinanceTransfer))).all() == []

    @pytest.mark.asyncio
    async def test_clear_repairs_the_net_worth_history(
        self, async_db_session: AsyncSession
    ) -> None:
        """Net-worth snapshots are derived rows the seeder inflated. Leaving
        them behind makes the chart keep drawing a curve for accounts that no
        longer exist."""
        await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER)
        await async_db_session.commit()
        seeded = (await async_db_session.exec(select(FinanceNetWorthSnapshot))).all()
        assert seeded, "expected the seed to write a net-worth series"

        await demo_seed.clear_demo(async_db_session, owner_user_id=OWNER)
        await async_db_session.commit()

        remaining = (await async_db_session.exec(select(FinanceNetWorthSnapshot))).all()
        assert all(row.net_worth_amount == 0 for row in remaining), (
            "net-worth history still reflects the deleted demo accounts"
        )

    @pytest.mark.asyncio
    async def test_clear_on_a_clean_install_is_a_noop(
        self, async_db_session: AsyncSession
    ) -> None:
        assert await demo_seed.clear_demo(async_db_session, owner_user_id=OWNER) == 0

    @pytest.mark.asyncio
    async def test_clear_unflags_surviving_transfer_legs(
        self, async_db_session: AsyncSession
    ) -> None:
        """A transfer pairing a real leg with a seeded one leaves the real
        transaction flagged out of reports; clearing must hand it back."""
        service = FinanceService(async_db_session)
        await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER)
        await async_db_session.commit()

        real_account = await service.create_manual_account(
            owner_user_id=OWNER,
            name="Real Checking",
            account_type="checking",
            classification="asset",
        )
        real_leg = await service.create_transaction(
            owner_user_id=OWNER,
            account_id=real_account.id,
            amount=-75_000,
            txn_date=date(2026, 6, 20),
            name="Transfer out",
        )
        # Any seeded transaction the detector has not already claimed: a leg
        # pairs with at most one transfer (partial-unique).
        paired = {
            leg
            for transfer in (await async_db_session.exec(select(FinanceTransfer))).all()
            for leg in (transfer.from_transaction_id, transfer.to_transaction_id)
        }
        demo_leg = next(
            t
            for t in (
                await async_db_session.exec(
                    select(FinanceTransaction).where(
                        FinanceTransaction.account_id != real_account.id
                    )
                )
            ).all()
            if t.id not in paired
        )
        transfer = FinanceTransfer(
            owner_user_id=OWNER,
            from_account_id=real_account.id,
            to_account_id=demo_leg.account_id,
            from_transaction_id=real_leg.id,
            to_transaction_id=demo_leg.id,
            amount=75_000,
            currency="usd",
            transfer_date=date(2026, 6, 20),
            match_method="auto_amount_date",
            confidence=90,
            status="confirmed",
        )
        async_db_session.add(transfer)
        await async_db_session.flush()
        real_leg.is_transfer = True
        real_leg.excluded_from_reports = True
        real_leg.transfer_group_id = transfer.id
        async_db_session.add(real_leg)
        await async_db_session.commit()

        await demo_seed.clear_demo(async_db_session, owner_user_id=OWNER)
        await async_db_session.commit()

        await async_db_session.refresh(real_leg)
        assert real_leg.is_transfer is False
        assert real_leg.excluded_from_reports is False
        assert real_leg.transfer_group_id is None
