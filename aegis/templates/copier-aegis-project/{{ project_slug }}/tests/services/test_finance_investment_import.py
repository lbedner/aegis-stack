"""Tests for the investment-activity ingestion lane (custodian trade ledgers,
as opposed to register CSVs which land in ``imports``).

Plain ``.py`` (finance-only stacks). Uses a small hand-crafted Optum-shaped
TSV fixture covering a conversion-in, ordinary buys, a reinvested dividend, a
recordkeeping fee, and a fund-exchange pair.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.investments.activity import replay_positions
from app.services.finance.domains.investments.loader import import_investment_activities
from app.services.finance.domains.investments.optum import (
    UnknownActivityTypeError,
    parse_optum_settled_transactions,
)
from app.services.finance.models import FinanceSecurity, FinanceTrade
from app.services.finance.service import FinanceService

_FIXTURES = Path(__file__).parent / "finance" / "fixtures"


def _sample_text() -> str:
    return (_FIXTURES / "optum_hsa_sample.tsv").read_text()


async def _account(session: AsyncSession) -> int:
    account = await FinanceService(session).create_manual_account(
        owner_user_id=1,
        name="HSA Investments",
        account_type="brokerage",
        classification="asset",
    )
    assert account.id is not None
    return account.id


class TestParseOptumSettledTransactions:
    def test_parses_every_row(self) -> None:
        activities = parse_optum_settled_transactions(_sample_text())
        assert len(activities) == 7

    def test_maps_canonical_types_and_signs(self) -> None:
        activities = parse_optum_settled_transactions(_sample_text())
        opening = next(
            a
            for a in activities
            if a.raw_type == "CONVERSION BALANCE"
            and a.security_name == "Schwab Small Cap Index"
        )
        assert opening.trade_type == "transfer_in"
        assert opening.units == Decimal("50.000")
        assert opening.amount_cents == 150_000  # positive: value entering

        fee = next(a for a in activities if a.raw_type == "SALE OF RECORDKEEPING FEE")
        assert fee.trade_type == "fee"
        assert fee.subtype == "recordkeeping_fee"
        assert fee.units == Decimal("-0.150")  # negative: shares leaving
        assert fee.amount_cents == -450

        reinvest = next(a for a in activities if a.raw_type == "REINVESTED DIVIDEND")
        assert reinvest.trade_type == "reinvest"
        assert reinvest.units == Decimal("3.500")
        assert reinvest.amount_cents == 13_300

        exchange_out = next(
            a for a in activities if a.raw_type == "SALE DUE TO FUND EXCHANGE"
        )
        assert exchange_out.trade_type == "sell"
        assert exchange_out.subtype == "fund_exchange"
        assert exchange_out.units == Decimal("-55.500")
        assert exchange_out.amount_cents == -160_950

        exchange_in = next(
            a for a in activities if a.raw_type == "PURCHASE DUE TO FUND EXCHANGE"
        )
        assert exchange_in.trade_type == "buy"
        assert exchange_in.subtype == "fund_exchange"
        assert exchange_in.units == Decimal("14.000")
        assert exchange_in.amount_cents == 160_950

    def test_unknown_activity_type_raises(self) -> None:
        bogus = (
            "Settled Transactions 01/01/2020 to 08/10/2026\n"
            "Transaction Date\tDescription\tType\tUnits\tPrice\tTotal Amount\n"
            "01/01/2024\tSome Fund\tMYSTERY MEAT\t1\t$1.00\t$1.00\n"
        )
        with pytest.raises(UnknownActivityTypeError):
            parse_optum_settled_transactions(bogus)


class TestReplayPositions:
    def test_replays_to_the_stated_ending_shares(self) -> None:
        activities = parse_optum_settled_transactions(_sample_text())
        positions = replay_positions(activities)
        # Schwab: conversion 50.000 + buy 2.500 - fee 0.150 + dividend 3.500
        assert positions["Schwab Small Cap Index"] == Decimal("55.850")
        # Admiral share class fully exchanged away -> zero.
        assert positions["Vanguard Total Int Stk Idx Adm"] == Decimal("0.000")
        # International fund receives the exchange-in.
        assert positions["Vanguard Total Intl Stk Idx I"] == Decimal("14.000")


class TestImportInvestmentActivities:
    @pytest.mark.asyncio
    async def test_loads_trades_securities_and_holdings(
        self, async_db_session: AsyncSession
    ) -> None:
        account_id = await _account(async_db_session)
        activities = parse_optum_settled_transactions(_sample_text())
        result = await import_investment_activities(
            async_db_session,
            owner_user_id=1,
            account_id=account_id,
            activities=activities,
            security_tickers={
                "Schwab Small Cap Index": "SWSSX",
                "Vanguard Total Int Stk Idx Adm": "VTIAX",
                "Vanguard Total Intl Stk Idx I": "VTSNX",
            },
        )
        assert result.trades_inserted == 7
        assert result.securities_created == 3

        trades = (
            await async_db_session.exec(
                select(FinanceTrade).where(FinanceTrade.account_id == account_id)
            )
        ).all()
        assert len(trades) == 7
        assert all(t.source == "csv" for t in trades)

        securities = (
            await async_db_session.exec(
                select(FinanceSecurity).where(
                    FinanceSecurity.ticker.in_(["SWSSX", "VTIAX", "VTSNX"])
                )
            )
        ).all()
        assert {s.ticker for s in securities} == {"SWSSX", "VTIAX", "VTSNX"}

        holding_ids = {t.security_id for t in trades}
        assert None not in holding_ids

    @pytest.mark.asyncio
    async def test_is_idempotent_on_reimport(
        self, async_db_session: AsyncSession
    ) -> None:
        account_id = await _account(async_db_session)
        activities = parse_optum_settled_transactions(_sample_text())
        tickers = {
            "Schwab Small Cap Index": "SWSSX",
            "Vanguard Total Int Stk Idx Adm": "VTIAX",
            "Vanguard Total Intl Stk Idx I": "VTSNX",
        }
        await import_investment_activities(
            async_db_session,
            owner_user_id=1,
            account_id=account_id,
            activities=activities,
            security_tickers=tickers,
        )
        second = await import_investment_activities(
            async_db_session,
            owner_user_id=1,
            account_id=account_id,
            activities=activities,
            security_tickers=tickers,
        )
        assert second.trades_inserted == 0
        assert second.trades_updated == 7

        trades = (
            await async_db_session.exec(
                select(FinanceTrade).where(FinanceTrade.account_id == account_id)
            )
        ).all()
        assert len(trades) == 7  # no duplicates on re-import

    @pytest.mark.asyncio
    async def test_reimport_without_tickers_reuses_the_same_securities(
        self, async_db_session: AsyncSession
    ) -> None:
        """The CLI's first import supplies real tickers (--ticker flags);
        the endpoint's later re-imports supply none (the UI has no field
        for them). The second call must resolve each fund back to the
        SAME security the first one created - by name, since there is no
        explicit ticker to key on this time - not mint a second
        placeholder-ticker row and repoint every trade at it. Confirmed
        live: doing exactly this doubled a real account's balance by
        creating five parallel holdings rows."""
        account_id = await _account(async_db_session)
        activities = parse_optum_settled_transactions(_sample_text())
        first = await import_investment_activities(
            async_db_session,
            owner_user_id=1,
            account_id=account_id,
            activities=activities,
            security_tickers={
                "Schwab Small Cap Index": "SWSSX",
                "Vanguard Total Int Stk Idx Adm": "VTIAX",
                "Vanguard Total Intl Stk Idx I": "VTSNX",
            },
        )
        assert first.securities_created == 3

        second = await import_investment_activities(
            async_db_session,
            owner_user_id=1,
            account_id=account_id,
            activities=activities,
            # No security_tickers - the endpoint never supplies one.
        )
        assert second.securities_created == 0
        assert second.securities_matched == 3
        assert second.trades_inserted == 0
        assert second.trades_updated == 7

        securities = (await async_db_session.exec(select(FinanceSecurity))).all()
        assert len(securities) == 3  # no duplicate MANUAL: rows
        assert {s.ticker for s in securities} == {"SWSSX", "VTIAX", "VTSNX"}


class TestRemovedAccountLeavesNoTrace:
    @pytest.mark.asyncio
    async def test_a_removed_accounts_trades_leave_the_all_accounts_lane(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The safe-test-import promise: import into a scratch account,
        remove the account, and nothing of it shows anywhere - including
        the unscoped trades feed, which (unlike transactions) used to keep
        serving a soft-deleted account's rows."""
        account_id = await _account(async_db_session)
        activities = parse_optum_settled_transactions(_sample_text())
        await import_investment_activities(
            async_db_session,
            owner_user_id=1,
            account_id=account_id,
            activities=activities,
        )
        assert len(await svc.list_trades(owner_user_id=1)) == 7

        assert await svc.soft_delete_account(account_id, owner_user_id=1)

        assert await svc.list_trades(owner_user_id=1) == []
