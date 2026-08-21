"""Quicken-export curation: categories and tags from CSV hints, and
promotion of streams the user's own categorization marks as bills.

A Quicken "All Transactions" report carries the user's category tree
("Bills & Utilities:Streaming:Television:Netflix") and tags on every row.
Dropping unknown hints (the old behavior) discards the user's curation;
these tests pin the new behavior: hints create categories + aliases, tags
become first-class tag rows, and recurring streams whose members live
under a bills-type category are promoted to subscriptions.
"""

from datetime import date

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection import promote_curated_streams
from app.services.finance.adapters.importers import imports
from app.services.finance.models import (
    FinanceCategoryAlias,
    FinanceRecurringStream,
    FinanceTag,
    FinanceTransaction,
    FinanceTransactionTag,
)
from app.services.finance.service import FinanceService

OWNER = 1


class TestCategoryFromHint:
    @pytest.mark.asyncio
    async def test_deep_quicken_path_creates_a_two_segment_category(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        category = await svc.get_or_create_category_from_hint(
            "Bills & Utilities:Streaming:Television:Netflix"
        )

        assert category is not None
        assert category.name == "Bills & Utilities:Streaming"
        assert category.classification == "expense"
        # The full path resolves through the alias table from now on.
        resolved = await svc.resolve_category_alias(
            "Bills & Utilities:Streaming:Television:Netflix"
        )
        assert resolved == category.id

    @pytest.mark.asyncio
    async def test_income_paths_classify_as_income(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        category = await svc.get_or_create_category_from_hint("Income:Paycheck")
        assert category is not None
        assert category.classification == "income"

    @pytest.mark.asyncio
    async def test_bracketed_transfer_hints_are_not_categories(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        assert await svc.get_or_create_category_from_hint("[TOTAL CHECKING]") is None

    @pytest.mark.asyncio
    async def test_paths_sharing_two_segments_share_one_category(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        first = await svc.get_or_create_category_from_hint(
            "Bills & Utilities:Streaming:Television:Netflix"
        )
        second = await svc.get_or_create_category_from_hint(
            "Bills & Utilities:Streaming:Music:Spotify"
        )
        assert first.id == second.id
        aliases = (
            await async_db_session.exec(
                select(FinanceCategoryAlias).where(
                    FinanceCategoryAlias.category_id == first.id
                )
            )
        ).all()
        assert len(aliases) == 2


def _quicken_csv(rows: list[str]) -> bytes:
    header = '"","Split","Date","Payee/Security","Category","Tags","Amount","Account"'
    return ("\n".join([header, *rows]) + "\n").encode()


async def _seed_csv_profiles(session: AsyncSession) -> None:
    from app.services.finance.models import FinanceImportProfile
    from app.services.finance.seeds.seed import CSV_IMPORT_PROFILES, DEFAULT_CURRENCIES

    svc = FinanceService(session)
    for currency in DEFAULT_CURRENCIES:
        await svc.get_or_create_currency(currency["code"])
    for profile in CSV_IMPORT_PROFILES:
        session.add(FinanceImportProfile(is_system=True, **profile))
    await session.flush()


class TestImportCarriesCuration:
    @pytest.mark.asyncio
    async def test_import_categorizes_and_tags_rows(
        self, async_db_session: AsyncSession
    ) -> None:
        await _seed_csv_profiles(async_db_session)
        data = _quicken_csv(
            [
                '"","","7/6/2026","Netflix","Bills & Utilities:Streaming:Television:Netflix","Family","-29.18","AMEX"',
                '"","","7/3/2026","Spotify","Bills & Utilities:Streaming","","-12.99","AMEX"',
            ]
        )

        result = await imports.import_file(
            async_db_session,
            owner_user_id=OWNER,
            file_name="quicken.csv",
            file_bytes=data,
        )
        assert result.rows_inserted == 2

        txns = (await async_db_session.exec(select(FinanceTransaction))).all()
        assert all(t.category_id is not None for t in txns)

        tags = (await async_db_session.exec(select(FinanceTag))).all()
        assert [t.name for t in tags] == ["Family"]
        links = (await async_db_session.exec(select(FinanceTransactionTag))).all()
        assert len(links) == 1


class TestStreamPromotion:
    @pytest.mark.asyncio
    async def test_bills_categorized_stream_becomes_a_subscription(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await svc.create_manual_account(
            owner_user_id=OWNER,
            name="Checking",
            account_type="checking",
            classification="asset",
        )
        category = await svc.get_or_create_category_from_hint(
            "Bills & Utilities:Television"
        )
        stream = FinanceRecurringStream(
            owner_user_id=OWNER,
            account_id=account.id,
            name="HBO Max",
            normalized_payee="HBO MAX",
            direction="outflow",
            frequency="monthly",
            average_amount=1849,
            amount_is_variable=True,
            currency="usd",
            status="mature",
            source="derived",
        )
        async_db_session.add(stream)
        await async_db_session.flush()
        for month in (5, 6, 7):
            await svc.create_transaction(
                owner_user_id=OWNER,
                account_id=account.id,
                amount=-1849,
                txn_date=date(2026, month, 16),
                name="HBO Max",
                category_id=category.id,
            )
        txns = (await async_db_session.exec(select(FinanceTransaction))).all()
        for txn in txns:
            txn.recurring_stream_id = stream.id
            async_db_session.add(txn)
        await async_db_session.flush()

        promoted = await promote_curated_streams(async_db_session, owner_user_id=OWNER)

        assert promoted == 1
        assert stream.is_subscription is True

    @pytest.mark.asyncio
    async def test_uncategorized_stream_is_left_alone(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await svc.create_manual_account(
            owner_user_id=OWNER,
            name="Checking",
            account_type="checking",
            classification="asset",
        )
        stream = FinanceRecurringStream(
            owner_user_id=OWNER,
            account_id=account.id,
            name="DOLLAR GENERAL",
            normalized_payee="DOLLAR GENERAL",
            direction="outflow",
            frequency="semi_monthly",
            average_amount=914,
            amount_is_variable=True,
            currency="usd",
            status="mature",
            source="derived",
        )
        async_db_session.add(stream)
        await async_db_session.flush()

        promoted = await promote_curated_streams(async_db_session, owner_user_id=OWNER)

        assert promoted == 0
        assert stream.is_subscription is False
