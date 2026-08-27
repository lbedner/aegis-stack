"""Tests for the manual investments layer (securities, holdings, portfolio value).

Plain ``.py`` (the ``app.services.finance`` import only resolves in
finance-selected stacks). Runs against the in-memory SQLite async session from
conftest (FK enforcement ON), exercising the same ``FinanceService`` the API,
CLI, and dashboard use.
"""

from datetime import date

import pytest

from app.services.finance.domains.investments.securities import market_value_cents
from app.services.finance.service import FinanceService

_E8 = 10**8  # quantity scale: shares stored as shares * 1e8


class TestMarketValue:
    def test_basic(self) -> None:
        # 10 shares @ $150.00 (price=15000, scale=2) -> $1,500.00 -> 150000 cents
        assert market_value_cents(10 * _E8, 15000, 2) == 150_000

    def test_fractional_shares(self) -> None:
        # 2.5 shares @ $10.00 -> $25.00
        assert market_value_cents(int(2.5 * _E8), 1000, 2) == 2_500

    def test_no_price_is_zero(self) -> None:
        assert market_value_cents(10 * _E8, None, 2) == 0

    def test_large_position_stays_exact(self) -> None:
        # 1,000,000 shares @ $1,234.5678 (scale 4). Float division of the
        # ~1e22 numerator would lose integer precision; integer math is exact.
        # value = 1_000_000 * 1234.5678 * 100 cents = 123_456_780_000
        assert market_value_cents(1_000_000 * _E8, 12_345_678, 4) == 123_456_780_000

    def test_negative_quantity_rounds_symmetrically(self) -> None:
        # Short position: 3 shares @ $10.005 (price=10005, scale=3) = $30.015.
        # Rounds half away from zero to -$30.02 -> -3002 cents.
        assert market_value_cents(-3 * _E8, 10_005, 3) == -3_002


class TestSecurities:
    @pytest.mark.asyncio
    async def test_get_or_create_is_idempotent_case_insensitive(
        self, svc: FinanceService
    ) -> None:
        first = await svc.get_or_create_security(ticker="aapl", name="Apple Inc.")
        again = await svc.get_or_create_security(ticker="AAPL")
        assert again.id == first.id  # same catalog row, not a duplicate
        assert first.ticker == "AAPL"  # normalized to upper


class TestProviderSecurityResolution:
    @pytest.mark.asyncio
    async def test_same_provider_id_updates_in_place(self, svc: FinanceService) -> None:
        first = await svc.upsert_provider_security(
            provider="plaid",
            provider_security_id="plaid-vti",
            ticker="VTI",
            name="Vanguard Total Stock Market ETF",
            figi="BBG000HT88C8",
            close_price=25_000,
        )
        again = await svc.upsert_provider_security(
            provider="plaid",
            provider_security_id="plaid-vti",
            ticker="VTI",
            name="Vanguard Total Stock Market",
            close_price=25_100,
        )
        assert again.id == first.id
        assert again.name == "Vanguard Total Stock Market"
        assert again.close_price == 25_100
        # A sync that omits the FIGI must not null out the merge key.
        assert again.figi == "BBG000HT88C8"

    @pytest.mark.asyncio
    async def test_partial_payload_does_not_erase_catalog_fields(
        self, svc: FinanceService
    ) -> None:
        """An activities row often carries only the provider security id
        (no pricing, sometimes no descriptives). Re-upserting from such a
        partial payload must not erase what a fuller sync already stored."""
        full = await svc.upsert_provider_security(
            provider="snaptrade",
            provider_security_id="sym-aapl",
            ticker="AAPL",
            name="Apple Inc.",
            security_type="cs",
            close_price=15_000,
        )
        partial = await svc.upsert_provider_security(
            provider="snaptrade",
            provider_security_id="sym-aapl",
        )
        assert partial.id == full.id
        assert partial.ticker == "AAPL"
        assert partial.name == "Apple Inc."
        assert partial.security_type == "cs"
        assert partial.close_price == 15_000

    @pytest.mark.asyncio
    async def test_figi_merges_across_providers(self, svc: FinanceService) -> None:
        """The FIN-25 contract: the same instrument reported by two
        aggregators resolves to ONE catalog row, keyed by FIGI."""
        plaid_row = await svc.upsert_provider_security(
            provider="plaid",
            provider_security_id="plaid-aapl",
            ticker="AAPL",
            name="Apple Inc.",
            figi="BBG000B9XRY4",
        )
        snaptrade_row = await svc.upsert_provider_security(
            provider="snaptrade",
            provider_security_id="c5f5b1b8-0000-4444-8888-123456789abc",
            ticker="AAPL",
            figi="BBG000B9XRY4",
            cusip="037833100",
        )
        assert snaptrade_row.id == plaid_row.id
        # First cataloger keeps the row identity; the newcomer fills gaps.
        assert snaptrade_row.provider == "plaid"
        assert snaptrade_row.provider_security_id == "plaid-aapl"
        assert snaptrade_row.cusip == "037833100"
        assert snaptrade_row.name == "Apple Inc."  # not clobbered by None

    @pytest.mark.asyncio
    async def test_cusip_fallback_when_figi_missing(self, svc: FinanceService) -> None:
        first = await svc.upsert_provider_security(
            provider="plaid",
            provider_security_id="plaid-bond",
            name="Some Corporate Bond",
            cusip="12345678X",
        )
        merged = await svc.upsert_provider_security(
            provider="snaptrade",
            provider_security_id="st-bond",
            cusip="12345678X",
        )
        assert merged.id == first.id

    @pytest.mark.asyncio
    async def test_no_identifiers_stays_provider_scoped(
        self, svc: FinanceService
    ) -> None:
        """Without a standard identifier there is nothing safe to merge on:
        two providers get two rows."""
        plaid_row = await svc.upsert_provider_security(
            provider="plaid", provider_security_id="plaid-mystery"
        )
        snaptrade_row = await svc.upsert_provider_security(
            provider="snaptrade", provider_security_id="st-mystery"
        )
        assert snaptrade_row.id != plaid_row.id


class TestHoldings:
    @pytest.mark.asyncio
    async def test_upsert_creates_and_syncs_account_balance(
        self, svc: FinanceService
    ) -> None:
        account = await svc.create_manual_account(
            owner_user_id=1,
            name="Brokerage",
            account_type="brokerage",
            classification="asset",
        )
        aapl = await svc.get_or_create_security(ticker="AAPL", name="Apple Inc.")
        await svc.upsert_holding(
            owner_user_id=1,
            account_id=account.id,
            security_id=aapl.id,
            as_of_date=date(2026, 7, 1),
            quantity_e8=10 * _E8,
            price=15000,
            price_scale=2,
            cost_basis=120_000,
        )
        # Manual holding -> account balance follows its holdings value ($1,500.00).
        refreshed = await svc.get_account(account.id, owner_user_id=1)
        assert refreshed is not None
        assert refreshed.current_balance == 150_000

    @pytest.mark.asyncio
    async def test_upsert_is_idempotent_on_date(self, svc: FinanceService) -> None:
        account = await svc.create_manual_account(
            owner_user_id=1,
            name="B",
            account_type="brokerage",
            classification="asset",
        )
        aapl = await svc.get_or_create_security(ticker="AAPL")
        for qty in (10, 12):  # same (account, security, date) -> update in place
            await svc.upsert_holding(
                owner_user_id=1,
                account_id=account.id,
                security_id=aapl.id,
                as_of_date=date(2026, 7, 1),
                quantity_e8=qty * _E8,
                price=15000,
            )
        holdings = await svc.list_current_holdings(
            owner_user_id=1, account_id=account.id
        )
        assert len(holdings) == 1  # updated, not duplicated
        holding, _security, value = holdings[0]
        assert holding.quantity_e8 == 12 * _E8
        assert value == 180_000  # 12 shares @ $150.00

    @pytest.mark.asyncio
    async def test_list_current_takes_latest_dated_snapshot(
        self, svc: FinanceService
    ) -> None:
        account = await svc.create_manual_account(
            owner_user_id=1,
            name="B",
            account_type="brokerage",
            classification="asset",
        )
        aapl = await svc.get_or_create_security(ticker="AAPL")
        await svc.upsert_holding(
            owner_user_id=1,
            account_id=account.id,
            security_id=aapl.id,
            as_of_date=date(2026, 6, 1),
            quantity_e8=10 * _E8,
            price=14000,
        )
        await svc.upsert_holding(
            owner_user_id=1,
            account_id=account.id,
            security_id=aapl.id,
            as_of_date=date(2026, 7, 1),
            quantity_e8=15 * _E8,
            price=15000,
        )
        holdings = await svc.list_current_holdings(owner_user_id=1)
        assert len(holdings) == 1
        holding, _security, value = holdings[0]
        assert holding.quantity_e8 == 15 * _E8  # latest date wins
        assert value == 225_000  # 15 shares @ $150.00

    @pytest.mark.asyncio
    async def test_excludes_holdings_of_soft_deleted_account(
        self, svc: FinanceService
    ) -> None:
        # Disconnecting a provider soft-deletes the account but leaves its
        # holding rows; those must not leak into portfolio listings/totals.
        account = await svc.create_manual_account(
            owner_user_id=1,
            name="Brokerage",
            account_type="brokerage",
            classification="asset",
        )
        aapl = await svc.get_or_create_security(ticker="AAPL")
        await svc.upsert_holding(
            owner_user_id=1,
            account_id=account.id,
            security_id=aapl.id,
            as_of_date=date(2026, 7, 1),
            quantity_e8=10 * _E8,
            price=15000,
        )
        assert len(await svc.list_current_holdings(owner_user_id=1)) == 1
        assert await svc.get_portfolio_value(owner_user_id=1) == 150_000

        await svc.soft_delete_account(account.id, owner_user_id=1)

        assert await svc.list_current_holdings(owner_user_id=1) == []
        assert await svc.get_portfolio_value(owner_user_id=1) == 0
