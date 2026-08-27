"""Valuation history: a dated series per source, and which one drives the balance.

``finance_valuation`` is keyed ``(account_id, as_of_date, source)``, so
Zillow, Redfin and an appraisal can all hold an opinion about the same day.
That makes "what is this house worth" ambiguous, and the account balance has
to answer it deterministically rather than by write order.
"""

from datetime import date

import pytest

from app.services.finance.domains.ledger.properties import (
    PROPERTY_ACCOUNT_TYPE,
    property_metadata,
)
from app.services.finance.service import FinanceService


async def _house(svc: FinanceService, name: str = "House Bedner"):
    return await svc.create_manual_account(
        name=name,
        account_type=PROPERTY_ACCOUNT_TYPE,
        classification="asset",
        owner_user_id=1,
    )


class TestBulkIngest:
    @pytest.mark.asyncio
    async def test_a_series_lands_as_dated_rows(self, svc: FinanceService) -> None:
        house = await _house(svc)

        result = await svc.ingest_valuations(
            house.id,
            owner_user_id=1,
            rows=[
                (date(2026, 8, 1), 71_120_000),
                (date(2026, 7, 1), 70_850_000),
                (date(2026, 6, 1), 71_150_000),
            ],
            source="zillow",
            is_estimate=True,
        )

        assert result.added == 3
        series = await svc.list_valuations(house.id, owner_user_id=1)
        assert [v.as_of_date for v in series] == [
            date(2026, 6, 1),
            date(2026, 7, 1),
            date(2026, 8, 1),
        ]
        assert {v.source for v in series} == {"zillow"}
        assert all(v.is_estimate for v in series)

    @pytest.mark.asyncio
    async def test_reingesting_the_same_series_updates_in_place(
        self, svc: FinanceService
    ) -> None:
        """A re-paste of a longer window must not double the history."""
        house = await _house(svc)
        rows = [(date(2026, 8, 1), 71_120_000)]

        await svc.ingest_valuations(
            house.id, owner_user_id=1, rows=rows, source="zillow"
        )
        again = await svc.ingest_valuations(
            house.id,
            owner_user_id=1,
            rows=[(date(2026, 8, 1), 71_500_000)],
            source="zillow",
        )

        series = await svc.list_valuations(house.id, owner_user_id=1)
        assert len(series) == 1
        assert series[0].value == 71_500_000
        assert again.added == 0 and again.updated == 1

    @pytest.mark.asyncio
    async def test_two_sources_coexist_on_one_date(self, svc: FinanceService) -> None:
        """Your own figure and a Zestimate for the same day are two rows,
        not a fight over one."""
        house = await _house(svc)

        await svc.ingest_valuations(
            house.id,
            owner_user_id=1,
            rows=[(date(2026, 8, 1), 71_120_000)],
            source="zillow",
        )
        await svc.ingest_valuations(
            house.id,
            owner_user_id=1,
            rows=[(date(2026, 8, 1), 69_000_000)],
            source="manual",
        )

        series = await svc.list_valuations(house.id, owner_user_id=1)
        assert len(series) == 2


class TestSourcePrecedence:
    """Which opinion the balance believes."""

    @pytest.mark.asyncio
    async def test_without_a_preference_the_newest_row_wins(
        self, svc: FinanceService, async_db_session
    ) -> None:
        house = await _house(svc)

        await svc.ingest_valuations(
            house.id,
            owner_user_id=1,
            rows=[(date(2026, 7, 1), 70_850_000)],
            source="zillow",
        )
        await svc.ingest_valuations(
            house.id,
            owner_user_id=1,
            rows=[(date(2026, 8, 1), 69_000_000)],
            source="manual",
        )

        await async_db_session.refresh(house)
        assert house.current_balance == 69_000_000

    @pytest.mark.asyncio
    async def test_a_preferred_source_decides_regardless_of_write_order(
        self, svc: FinanceService, async_db_session
    ) -> None:
        """The bug this prevents: a second source landing later and
        silently repricing the largest asset on the balance sheet."""
        house = await _house(svc)
        await svc.set_property_details(
            house.id, owner_user_id=1, preferred_valuation_source="zillow"
        )

        await svc.ingest_valuations(
            house.id,
            owner_user_id=1,
            rows=[(date(2026, 8, 1), 71_120_000)],
            source="zillow",
        )
        await svc.ingest_valuations(
            house.id,
            owner_user_id=1,
            rows=[(date(2026, 8, 15), 69_000_000)],
            source="manual",
        )

        await async_db_session.refresh(house)
        assert house.current_balance == 71_120_000  # the preferred source

    @pytest.mark.asyncio
    async def test_the_preference_falls_back_when_it_has_nothing(
        self, svc: FinanceService, async_db_session
    ) -> None:
        """A preference set before that source has ever posted must not
        blank the balance."""
        house = await _house(svc)
        await svc.set_property_details(
            house.id, owner_user_id=1, preferred_valuation_source="kbb"
        )

        await svc.ingest_valuations(
            house.id,
            owner_user_id=1,
            rows=[(date(2026, 8, 1), 71_120_000)],
            source="zillow",
        )

        await async_db_session.refresh(house)
        assert house.current_balance == 71_120_000

    @pytest.mark.asyncio
    async def test_the_preference_is_stored_on_the_property(
        self, svc: FinanceService
    ) -> None:
        house = await _house(svc)

        await svc.set_property_details(
            house.id, owner_user_id=1, preferred_valuation_source="zillow"
        )

        meta = property_metadata(house.metadata_)
        assert meta is not None
        assert meta.preferred_valuation_source == "zillow"
