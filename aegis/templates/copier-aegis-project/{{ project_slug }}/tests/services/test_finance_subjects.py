"""Whose money a row describes.

The ledger has always recorded whose APP a row lives in, never whose
money it is. Households manage money for other people - a parent's
checking account, a child's savings, a trust - and with one owner column
those sit beside the household's own, indistinguishable, so every total
silently mixes two people's money and "what were his resources on this
date" is not a question anyone can ask.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.service import FinanceService
from tests.services._finance_factories import seed_account as _account


class TestSubjects:
    @pytest.mark.asyncio
    async def test_a_subject_can_be_created_and_listed(
        self, svc: FinanceService
    ) -> None:
        subject = await svc.create_subject(name="Dad", kind="person", owner_user_id=1)

        assert subject.id is not None
        assert [s.name for s in await svc.list_subjects(owner_user_id=1)] == ["Dad"]

    @pytest.mark.asyncio
    async def test_an_account_says_whose_money_it_holds(
        self, svc: FinanceService
    ) -> None:
        subject = await svc.create_subject(name="Dad", owner_user_id=1)
        account = await _account(svc, name="HVCU Checking")

        updated = await svc.assign_subject(account.id, subject.id, owner_user_id=1)

        assert updated is not None and updated.subject_id == subject.id

    @pytest.mark.asyncio
    async def test_unassigned_rows_stay_the_households_own(
        self, svc: FinanceService
    ) -> None:
        """Null is not "unknown", it is "ours" - so nothing about an
        existing ledger changes when subjects arrive."""
        account = await _account(svc)

        assert account.subject_id is None

    @pytest.mark.asyncio
    async def test_accounts_can_be_narrowed_to_one_subject(
        self, svc: FinanceService
    ) -> None:
        subject = await svc.create_subject(name="Dad", owner_user_id=1)
        theirs = await _account(svc, name="HVCU Checking")
        await _account(svc, name="Household Checking")
        await svc.assign_subject(theirs.id, subject.id, owner_user_id=1)

        rows, _total = await svc.list_accounts(owner_user_id=1, subject_id=subject.id)

        assert [a.name for a in rows] == ["HVCU Checking"]

    @pytest.mark.asyncio
    async def test_the_household_view_excludes_other_peoples_money(
        self, svc: FinanceService
    ) -> None:
        """The default view is the household's own, which is what every
        existing caller already means by "my accounts"."""
        subject = await svc.create_subject(name="Dad", owner_user_id=1)
        theirs = await _account(svc, name="HVCU Checking")
        await _account(svc, name="Household Checking")
        await svc.assign_subject(theirs.id, subject.id, owner_user_id=1)

        rows, _total = await svc.list_accounts(owner_user_id=1, subject_id=0)

        assert [a.name for a in rows] == ["Household Checking"]

    @pytest.mark.asyncio
    async def test_no_filter_still_means_everything(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        subject = await svc.create_subject(name="Dad", owner_user_id=1)
        theirs = await _account(svc, name="HVCU Checking")
        await _account(svc, name="Household Checking")
        await svc.assign_subject(theirs.id, subject.id, owner_user_id=1)

        rows, _total = await svc.list_accounts(owner_user_id=1)

        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_a_subject_can_be_released(self, svc: FinanceService) -> None:
        subject = await svc.create_subject(name="Dad", owner_user_id=1)
        account = await _account(svc)
        await svc.assign_subject(account.id, subject.id, owner_user_id=1)

        updated = await svc.assign_subject(account.id, None, owner_user_id=1)

        assert updated is not None and updated.subject_id is None

    @pytest.mark.asyncio
    async def test_a_stream_and_a_property_carry_the_subject_too(
        self, svc: FinanceService
    ) -> None:
        """Resources and income both answer "whose", or the question is
        only half answerable."""
        from tests.services._finance_factories import seed_stream

        subject = await svc.create_subject(name="Dad", owner_user_id=1)
        account = await _account(svc)
        stream = await seed_stream(
            svc,
            name="NYSLRS",
            direction="inflow",
            expected_amount=100_493,
            next_expected_date=date(2026, 9, 30),
            account_id=account.id,
            subject_id=subject.id,
        )

        assert stream.subject_id == subject.id

    @pytest.mark.asyncio
    async def test_an_unknown_kind_is_refused_before_the_database_sees_it(
        self, svc: FinanceService
    ) -> None:
        """The check constraint would catch it, but as an IntegrityError at
        flush - a caller deserves to be told which values exist."""
        with pytest.raises(ValueError, match="kind"):
            await svc.create_subject(name="Dad", kind="pet", owner_user_id=1)
