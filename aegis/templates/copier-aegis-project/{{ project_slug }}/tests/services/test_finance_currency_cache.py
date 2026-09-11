"""A currency lookup is resolved once per session, not once per row.

``get_or_create_currency`` is called on every path that writes a row
carrying a currency FK - every security, price, holding, trade, budget
line, recurring stream, and every row of a provider sync loop. Each call
issued its own SELECT for a table that holds a handful of immutable rows,
which is the single largest source of repeated statements in the suite.
"""

from __future__ import annotations

import pytest
from queryspy import assert_max_queries
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.ledger.accounts import get_or_create_currency


class TestCurrencyLookupIsCachedPerSession:
    @pytest.mark.asyncio
    async def test_repeated_lookups_issue_one_select(
        self, async_db_session: AsyncSession
    ) -> None:
        first = await get_or_create_currency(async_db_session, "usd")

        # The insert for a brand new currency is one statement; every
        # lookup after it must add none.
        with assert_max_queries(0):
            for _ in range(5):
                again = await get_or_create_currency(async_db_session, "usd")
                assert again.id == first.id

    @pytest.mark.asyncio
    async def test_a_different_code_is_still_looked_up(
        self, async_db_session: AsyncSession
    ) -> None:
        usd = await get_or_create_currency(async_db_session, "usd")
        eur = await get_or_create_currency(async_db_session, "eur")
        assert usd.code == "usd"
        assert eur.code == "eur"
        assert usd.id != eur.id

    @pytest.mark.asyncio
    async def test_the_cache_does_not_leak_across_sessions(self, async_engine) -> None:
        """A cache keyed on the session must die with it, or a rolled back
        currency would be handed to the next request as if it existed."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        maker = async_sessionmaker(async_engine, class_=AsyncSession)
        async with maker() as one:
            await get_or_create_currency(one, "usd")
            assert one.info.get("finance_currency_cache")
        async with maker() as two:
            assert not two.info.get("finance_currency_cache")


    @pytest.mark.asyncio
    async def test_a_rolled_back_savepoint_does_not_poison_the_cache(
        self, async_db_session: AsyncSession
    ) -> None:
        """Provider sync wraps each connection in a SAVEPOINT. A currency
        created inside one that then rolls back must not be handed to the
        next connection: the instance is expunged, and using it detaches
        every row that referenced it."""
        async with async_db_session.begin_nested() as savepoint:
            await get_or_create_currency(async_db_session, "jpy")
            await savepoint.rollback()

        after = await get_or_create_currency(async_db_session, "jpy")
        assert after in async_db_session
        assert after.code == "jpy"
