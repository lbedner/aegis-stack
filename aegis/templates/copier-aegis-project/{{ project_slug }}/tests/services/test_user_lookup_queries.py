"""``get_user_by_id`` is a primary-key lookup, so it must go through the
session's identity map rather than issuing a fresh SELECT every call.

Every write path in ``UserService`` re-reads the user first - update,
deactivate, verify, reset - so a single request routinely asks the
database for the same row two or three times.
"""

from __future__ import annotations

import pytest
from queryspy import assert_max_queries
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.auth.users import UserService


class TestUserByIdUsesTheIdentityMap:
    @pytest.mark.asyncio
    async def test_second_lookup_issues_no_sql(
        self, async_db_session: AsyncSession, user_factory
    ) -> None:
        created = await user_factory()
        service = UserService(async_db_session)

        first = await service.get_user_by_id(created.id)
        assert first is not None

        with assert_max_queries(0):
            again = await service.get_user_by_id(created.id)
        assert again is not None
        assert again.id == created.id

    @pytest.mark.asyncio
    async def test_a_soft_deleted_user_is_still_invisible(
        self, async_db_session: AsyncSession, user_factory
    ) -> None:
        """The identity map has no idea about ``deleted_at``; the filter has
        to survive the rewrite or soft delete stops working."""
        created = await user_factory()
        service = UserService(async_db_session)
        assert await service.delete_user(created.id) is True
        assert await service.get_user_by_id(created.id) is None

    @pytest.mark.asyncio
    async def test_a_missing_user_is_none(self, async_db_session: AsyncSession) -> None:
        service = UserService(async_db_session)
        assert await service.get_user_by_id(999_999) is None


class TestUsersByIds:
    @pytest.mark.asyncio
    async def test_many_users_in_one_query(
        self, async_db_session: AsyncSession, user_factory
    ) -> None:
        """A table of spenders names every row: one IN query, never a
        lookup per row; deleted and unknown ids are simply absent."""
        kept = await user_factory()
        other = await user_factory()
        gone = await user_factory()
        service = UserService(async_db_session)
        await service.delete_user(gone.id)

        with assert_max_queries(1):
            unknown = max(kept.id, other.id, gone.id) + 1_000
            found = await service.get_users_by_ids(
                [kept.id, other.id, gone.id, unknown]
            )
        assert set(found) == {kept.id, other.id}
        assert found[kept.id].email == kept.email
