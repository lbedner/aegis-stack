"""Envelopes: virtual sub-accounts (an allowance the kid draws down).

Same account-as-carrier design as goals - hidden manual account, balance
and history on valuations - but balances move BOTH directions and there
is no target/progress framing. The net-worth/listing exclusion is pinned
here too: envelope money physically sits in real cash already.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.planning.envelopes import (
    ENVELOPE_ACCOUNT_TYPE,
    EnvelopeMeta,
    envelope_metadata,
    set_envelope_metadata,
)
from app.services.finance.service import FinanceService
from tests.services._finance_factories import seed_stream


class TestMetadataContract:
    def test_round_trip(self) -> None:
        written = set_envelope_metadata(
            {"neighbour": "kept"}, monthly_credit=4_000, auto_credit=True
        )
        meta = envelope_metadata(written)
        assert meta == EnvelopeMeta(monthly_credit=4_000, auto_credit=True)
        assert written["neighbour"] == "kept"

    def test_stored_shape_is_json_native(self) -> None:
        """The stored form is the storage contract: plain JSON keys and
        values, no model objects leaking into ``metadata_``."""
        written = set_envelope_metadata(
            None, monthly_credit=4_000, auto_credit=True, cadence="weekly"
        )
        assert written == {
            "envelope": True,
            "envelope_monthly_credit": 4_000,
            "envelope_auto_credit": True,
            "envelope_credit_cadence": "weekly",
        }

    def test_defaults(self) -> None:
        meta = envelope_metadata(set_envelope_metadata(None))
        assert meta is not None
        assert meta.monthly_credit is None
        assert meta.auto_credit is False

    def test_not_an_envelope_reads_none(self) -> None:
        assert envelope_metadata(None) is None
        assert envelope_metadata({"goal_target_amount": 100}) is None

    def test_negative_credit_rejected(self) -> None:
        with pytest.raises(ValueError):
            set_envelope_metadata(None, monthly_credit=-1)


class TestEnvelopeAccounts:
    @pytest.mark.asyncio
    async def test_create_and_exclusion_pins(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await svc.create_manual_account(
            owner_user_id=1,
            name="Checking",
            account_type="checking",
            classification="asset",
            current_balance=100_000,
        )
        envelope = await svc.create_envelope(
            owner_user_id=1, name="Allowance", monthly_credit=4_000
        )
        await async_db_session.commit()
        assert envelope.account_type == ENVELOPE_ACCOUNT_TYPE
        assert envelope.is_hidden is True

        net_worth = await svc.get_net_worth(owner_user_id=1)
        assert net_worth.total_assets_amount == 100_000
        accounts, total = await svc.list_accounts(owner_user_id=1)
        assert total == 1

    @pytest.mark.asyncio
    async def test_credit_and_spend_walk_the_balance(self, svc: FinanceService) -> None:
        envelope = await svc.create_envelope(
            owner_user_id=1, name="Allowance", monthly_credit=4_000
        )
        await svc.credit_envelope(
            envelope.id, amount=4_000, owner_user_id=1, when=date(2026, 8, 1)
        )
        await svc.spend_from_envelope(
            envelope.id,
            amount=1_250,
            owner_user_id=1,
            when=date(2026, 8, 5),
            note="Roblox",
        )
        refreshed = await svc.get_account(envelope.id, owner_user_id=1)
        assert refreshed is not None
        assert refreshed.current_balance == 2_750

    @pytest.mark.asyncio
    async def test_spending_past_zero_goes_negative_not_clamped(
        self, svc: FinanceService
    ) -> None:
        """Borrowing against next month is a fact worth showing red, not
        an error worth hiding."""
        envelope = await svc.create_envelope(owner_user_id=1, name="Allowance")
        await svc.spend_from_envelope(
            envelope.id, amount=500, owner_user_id=1, when=date(2026, 8, 5)
        )
        refreshed = await svc.get_account(envelope.id, owner_user_id=1)
        assert refreshed is not None
        assert refreshed.current_balance == -500

    @pytest.mark.asyncio
    async def test_list_envelopes_finds_only_envelopes(
        self, svc: FinanceService
    ) -> None:
        await svc.create_envelope(owner_user_id=1, name="Allowance")
        await svc.create_virtual_goal(
            owner_user_id=1, name="Vacation", target_amount=300_000
        )
        envelopes = await svc.list_envelopes(owner_user_id=1)
        assert [e.name for e in envelopes] == ["Allowance"]


class TestAutoCredit:
    @pytest.mark.asyncio
    async def test_books_once_per_month(self, svc: FinanceService) -> None:
        envelope = await svc.create_envelope(
            owner_user_id=1, name="Allowance", monthly_credit=4_000
        )
        await svc.set_envelope_auto_credit(envelope.id, True, owner_user_id=1)
        first = await svc.auto_credit_envelopes(owner_user_id=1, today=date(2026, 9, 1))
        again = await svc.auto_credit_envelopes(
            owner_user_id=1, today=date(2026, 9, 20)
        )
        nxt = await svc.auto_credit_envelopes(owner_user_id=1, today=date(2026, 10, 1))
        assert (first, again, nxt) == (1, 0, 1)
        refreshed = await svc.get_account(envelope.id, owner_user_id=1)
        assert refreshed is not None
        assert refreshed.current_balance == 8_000

    @pytest.mark.asyncio
    async def test_auto_off_or_no_credit_skipped(self, svc: FinanceService) -> None:
        await svc.create_envelope(
            owner_user_id=1, name="Quiet", monthly_credit=4_000
        )  # auto off (default)
        no_amount = await svc.create_envelope(owner_user_id=1, name="Empty")
        await svc.set_envelope_auto_credit(no_amount.id, True, owner_user_id=1)
        booked = await svc.auto_credit_envelopes(
            owner_user_id=1, today=date(2026, 9, 1)
        )
        assert booked == 0


class TestEnvelopesJoinTheEquation:
    """Auto-credit envelopes are spoken-for money: the allowance leaves
    the spendable month whether or not anyone clicks."""

    @pytest.mark.asyncio
    async def test_auto_envelopes_subtract_from_the_month(
        self, svc: FinanceService
    ) -> None:
        account = await svc.create_manual_account(
            owner_user_id=1,
            name="Checking",
            account_type="checking",
            classification="asset",
        )
        await seed_stream(
            svc,
            name="Paycheck",
            direction="inflow",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        auto = await svc.create_envelope(
            owner_user_id=1, name="Allowance", monthly_credit=4_000
        )
        await svc.set_envelope_auto_credit(auto.id, True, owner_user_id=1)
        # A manual envelope asks nothing of the equation.
        await svc.create_envelope(
            owner_user_id=1, name="Repairs", monthly_credit=10_000
        )

        stats = (await svc.budget_summary(owner_user_id=1)).stats

        assert stats.envelopes_total == 4_000
        assert stats.month_net == 500_000 - 4_000
        assert (
            stats.income_total
            - stats.fixed_total
            - stats.flexible_allocated
            - stats.goals_total
            - stats.envelopes_total
            == stats.month_net
        )


class TestWeeklyCadence:
    """The allowance is weekly in this house: envelopes carry a credit
    cadence, the job books per period (idempotent within it), and the
    equation counts the monthly equivalent."""

    def test_metadata_round_trips_cadence(self) -> None:
        meta = envelope_metadata(
            set_envelope_metadata(None, monthly_credit=1_000, cadence="weekly")
        )
        assert meta is not None and meta.cadence == "weekly"
        # Old envelopes with no cadence read monthly.
        legacy = envelope_metadata(set_envelope_metadata(None, monthly_credit=1_000))
        assert legacy is not None and legacy.cadence == "monthly"
        with pytest.raises(ValueError):
            set_envelope_metadata(None, cadence="fortnightly-ish")

    @pytest.mark.asyncio
    async def test_weekly_books_each_week_once(self, svc: FinanceService) -> None:
        envelope = await svc.create_envelope(
            owner_user_id=1, name="Allowance", monthly_credit=1_000, cadence="weekly"
        )
        await svc.set_envelope_auto_credit(envelope.id, True, owner_user_id=1)

        # 2026-08-10 is a Monday; the 12th is the same week; the 17th is next.
        monday = await svc.auto_credit_envelopes(
            owner_user_id=1, today=date(2026, 8, 10)
        )
        midweek = await svc.auto_credit_envelopes(
            owner_user_id=1, today=date(2026, 8, 12)
        )
        next_week = await svc.auto_credit_envelopes(
            owner_user_id=1, today=date(2026, 8, 17)
        )
        assert (monday, midweek, next_week) == (1, 0, 1)
        refreshed = await svc.get_account(envelope.id, owner_user_id=1)
        assert refreshed is not None
        assert refreshed.current_balance == 2_000

    @pytest.mark.asyncio
    async def test_the_equation_counts_the_monthly_equivalent(
        self, svc: FinanceService
    ) -> None:
        account = await svc.create_manual_account(
            owner_user_id=1,
            name="Checking",
            account_type="checking",
            classification="asset",
        )
        await seed_stream(
            svc,
            name="Paycheck",
            direction="inflow",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        envelope = await svc.create_envelope(
            owner_user_id=1, name="Allowance", monthly_credit=1_000, cadence="weekly"
        )
        await svc.set_envelope_auto_credit(envelope.id, True, owner_user_id=1)

        stats = (await svc.budget_summary(owner_user_id=1)).stats
        # $10/week at the same weekly->monthly factor bills use.
        assert stats.envelopes_total == int(1_000 * 52 / 12)


class TestSeedMoney:
    @pytest.mark.asyncio
    async def test_an_envelope_can_be_born_with_money(
        self, svc: FinanceService
    ) -> None:
        envelope = await svc.create_envelope(
            owner_user_id=1,
            name="Vacation spending",
            starting_balance=300_000,
        )
        refreshed = await svc.get_account(envelope.id, owner_user_id=1)
        assert refreshed is not None
        assert refreshed.current_balance == 300_000

    @pytest.mark.asyncio
    async def test_no_seed_stays_zero(self, svc: FinanceService) -> None:
        envelope = await svc.create_envelope(owner_user_id=1, name="Allowance")
        refreshed = await svc.get_account(envelope.id, owner_user_id=1)
        assert refreshed is not None
        assert refreshed.current_balance == 0
