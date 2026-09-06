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
    FinanceInsight,
    FinanceNetWorthSnapshot,
    FinancePendingChange,
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


class TestTheHouseholdIsLegible:
    """The seed exists to make every surface show something.

    A household with a large idle balance and four merchants demos
    nothing: the projection cannot dip, the donut has no shape, and half
    the app looks like an empty state. These pin the properties that make
    the screenshots worth taking, and they are about SHAPE, not about
    exact amounts - the amounts should stay free to be tuned.
    """

    ANCHOR = date(2026, 7, 1)
    MONTHS = 12

    def _ledger(self) -> tuple[demo_seed.PlannedTransaction, ...]:
        return demo_seed.build_demo_ledger(anchor=self.ANCHOR, months=self.MONTHS)

    def test_checking_does_not_quietly_accumulate_a_fortune(self) -> None:
        """The one number that decides whether the app can show tension.

        Income used to exceed outflow by thousands a month with nowhere
        to go, so checking drifted to $55k. No bill sequence dips that
        below zero, which means the Projected tab, the cash-runway rule
        and the minimum-payment rule have nothing to say no matter what
        else is seeded.
        """
        balance = 0
        for entry in self._ledger():
            if entry.account_key == "checking":
                balance += entry.amount

        opening = next(
            a.opening_balance or 0
            for a in demo_seed.DEMO_ACCOUNTS
            if a.key == "checking"
        )
        closing = opening + balance
        assert closing < 1_000_000, (
            f"checking closes at ${closing / 100:,.0f}: too fat to ever dip"
        )

    def test_two_people_are_paid_on_different_rhythms(self) -> None:
        """One salary on one cadence is a single-earner household, and it
        makes every paycheck land on the same two days."""
        income = {entry.name for entry in self._ledger() if entry.category == "INCOME"}
        assert len(income) >= 2, f"only one income source: {income}"

    def test_spending_covers_more_than_a_handful_of_categories(self) -> None:
        """The donut folds its tail into "Other" - with four categories
        that is the whole chart."""
        spend = {
            entry.category
            for entry in self._ledger()
            if entry.amount < 0 and entry.category
        }
        assert len(spend) >= 8, f"only {len(spend)} spending categories: {spend}"

    def test_there_is_enough_activity_to_look_like_a_real_ledger(self) -> None:
        """Two adults transact several times a day. One row a day leaves
        every chart sparse."""
        ledger = self._ledger()
        span_days = (
            max(e.txn_date for e in ledger) - min(e.txn_date for e in ledger)
        ).days
        assert len(ledger) / max(span_days, 1) >= 3, (
            f"{len(ledger)} rows over {span_days} days is too thin"
        )

    def test_a_card_is_carried_rather_than_cleared_every_month(self) -> None:
        """A card paid in full every month has no payoff story, no
        interest, and nothing for the credit rules to notice."""
        names = {entry.name for entry in self._ledger()}
        assert any("Interest" in name for name in names), (
            "no interest charge: nothing is being carried"
        )


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
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """``--reset`` scopes its deletes to seeded rows, never the user's."""
        real = await svc.create_manual_account(
            owner_user_id=OWNER,
            name="Chase Total Checking",  # same name as a demo account
            account_type="checking",
            classification="asset",
        )
        real_txn = await svc.create_transaction(
            owner_user_id=OWNER,
            account_id=real.id,
            amount=-1234,
            txn_date=date(2026, 6, 1),
            name="Whole Foods Market",
        )
        await async_db_session.commit()

        await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER, reset=True)
        await async_db_session.commit()

        survivor = await svc.get_account(real.id, owner_user_id=OWNER)
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
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await svc.create_manual_account(
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
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """A transfer pairing a real leg with a seeded one leaves the real
        transaction flagged out of reports; clearing must hand it back."""
        await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER)
        await async_db_session.commit()

        real_account = await svc.create_manual_account(
            owner_user_id=OWNER,
            name="Real Checking",
            account_type="checking",
            classification="asset",
        )
        real_leg = await svc.create_transaction(
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


class TestTheReviewTabHasWork:
    """Review is the tab you clear, and the seed used to leave it clear.

    Every row was categorized, every payee named, nothing proposed, and
    the planted anomalies sat outside the rules' lookback windows. Four
    sub-tabs, all empty states. A demo of a review queue needs a queue.
    """

    ANCHOR = date(2026, 9, 5)

    def test_some_rows_arrive_uncategorized(self) -> None:
        ledger = demo_seed.build_demo_ledger(anchor=self.ANCHOR, months=12)
        bare = [e for e in ledger if e.category is None and e.amount < 0]
        assert len(bare) >= 3, "nothing for the Uncategorized queue"

    def test_some_rows_arrive_with_no_payee(self) -> None:
        ledger = demo_seed.build_demo_ledger(anchor=self.ANCHOR, months=12)
        assert any(not e.payee for e in ledger), "nothing for the No payee queue"

    @pytest.mark.asyncio
    async def test_no_payee_holds_the_bare_rows_and_not_the_whole_ledger(
        self, async_db_session: AsyncSession
    ) -> None:
        """Imports leave every payee unassigned, so without curation the
        queue is the ledger. The seed names what a person would have
        named, and leaves only what a bank named unusably."""
        await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER, months=12)

        unnamed = [
            t
            for t in await _transactions(async_db_session)
            if t.merchant_id is None and t.amount < 0 and not t.is_transfer
        ]

        assert 1 <= len(unnamed) <= 20, f"{len(unnamed)} rows in No payee"

    @pytest.mark.asyncio
    async def test_proposals_are_waiting_for_approval(
        self, async_db_session: AsyncSession
    ) -> None:
        """Without the AI service nothing can file a proposal, so Approvals
        - the highest-stakes queue - screenshots as an empty state."""
        await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER, months=12)

        pending = (
            await async_db_session.exec(
                select(FinancePendingChange).where(
                    FinancePendingChange.proposed_by_agent == "demo_seed"
                )
            )
        ).all()

        assert len(pending) >= 2
        assert {p.status for p in pending} == {"pending"}
        assert {p.change_type for p in pending} >= {
            "transaction.categorize",
            "transaction.assign_payee",
        }
        # The payee proposal is about a row the bank named unusably, never
        # a transfer leg - a transfer already has its counterparty.
        payee = next(p for p in pending if p.change_type == "transaction.assign_payee")
        target = await async_db_session.get(
            FinanceTransaction, payee.payload["transaction_id"]
        )
        assert target is not None and not target.is_transfer
        assert target.name.startswith(("POS DEBIT", "ACH WITHDRAWAL"))

    @pytest.mark.asyncio
    async def test_the_planted_anomalies_actually_fire(
        self, async_db_session: AsyncSession
    ) -> None:
        """A one-off three months back is invisible to a rule with a 35-day
        window. What the seed plants has to land where the rules look."""
        await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER, months=12)

        kinds = {
            i.insight_type
            for i in (await async_db_session.exec(select(FinanceInsight))).all()
        }

        assert {"fee_charged", "large_transaction"} <= kinds, kinds

    @pytest.mark.asyncio
    async def test_clear_leaves_another_owners_proposals_alone(
        self, async_db_session: AsyncSession
    ) -> None:
        """The agent name says WHAT filed it; the owner says WHOSE it is.
        One household clearing its demo must not take a neighbour's."""
        await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER, months=12)
        neighbour = FinancePendingChange(
            owner_user_id=OWNER + 1,
            change_type="transaction.categorize",
            payload={"transaction_id": 1, "category_id": 1},
            proposed_by_agent="demo_seed",
        )
        async_db_session.add(neighbour)
        await async_db_session.flush()

        await demo_seed.clear_demo(async_db_session, owner_user_id=OWNER)

        left = (
            await async_db_session.exec(
                select(FinancePendingChange).where(
                    FinancePendingChange.proposed_by_agent == "demo_seed"
                )
            )
        ).all()
        assert [p.owner_user_id for p in left] == [OWNER + 1]

    @pytest.mark.asyncio
    async def test_clear_takes_the_proposals_with_it(
        self, async_db_session: AsyncSession
    ) -> None:
        await demo_seed.seed_demo(async_db_session, owner_user_id=OWNER, months=12)
        await demo_seed.clear_demo(async_db_session, owner_user_id=OWNER)

        left = (
            await async_db_session.exec(
                select(FinancePendingChange).where(
                    FinancePendingChange.proposed_by_agent == "demo_seed"
                )
            )
        ).all()
        assert left == []
