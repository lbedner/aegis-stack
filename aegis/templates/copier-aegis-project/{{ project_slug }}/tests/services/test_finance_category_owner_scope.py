"""A category someone creates is theirs; seeds are everyone's.

``finance_category`` was designed for this - ``owner_user_id`` NULL is a
shared seed row, a user's rows carry their id, and ``slug`` is unique per
scope - but every writer created shared rows and every reader returned all
of them. In an auth stack one user's typed or imported category then
appeared in every other user's picker.

A ``None`` owner is the standalone (no auth) install: one user, so its rows
stay shared and its reads stay unfiltered, exactly as before.
"""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.service import FinanceService

ALICE, BOB = 1, 2


async def _names(svc: FinanceService, owner: int | None) -> set[str]:
    return {c.name for c in await svc.list_categories(owner_user_id=owner)}


@pytest.mark.asyncio
async def test_each_owner_sees_the_seeds_and_their_own(
    async_db_session: AsyncSession,
) -> None:
    svc = FinanceService(async_db_session)
    await svc.get_or_create_category_from_hint("Shared:Seed")
    await svc.get_or_create_category_from_hint("Alice:Therapy", owner_user_id=ALICE)
    await svc.get_or_create_category_from_hint("Bob:Poker", owner_user_id=BOB)

    assert await _names(svc, ALICE) == {"Shared:Seed", "Alice:Therapy"}
    assert await _names(svc, BOB) == {"Shared:Seed", "Bob:Poker"}


@pytest.mark.asyncio
async def test_a_created_category_is_owned_by_whoever_made_it(
    async_db_session: AsyncSession,
) -> None:
    svc = FinanceService(async_db_session)

    category = await svc.get_or_create_category_from_hint(
        "Kids:Activities", owner_user_id=ALICE
    )

    assert category is not None
    assert category.owner_user_id == ALICE


@pytest.mark.asyncio
async def test_the_same_name_from_two_owners_is_two_categories(
    async_db_session: AsyncSession,
) -> None:
    """Get-or-create resolves within the caller's scope, so Bob typing a
    name Alice already used makes his own row instead of borrowing hers."""
    svc = FinanceService(async_db_session)

    alices = await svc.get_or_create_category_from_hint("Gifts", owner_user_id=ALICE)
    bobs = await svc.get_or_create_category_from_hint("Gifts", owner_user_id=BOB)

    assert alices is not None and bobs is not None
    assert alices.id != bobs.id
    assert bobs.owner_user_id == BOB


@pytest.mark.asyncio
async def test_a_seed_is_reused_rather_than_copied(
    async_db_session: AsyncSession,
) -> None:
    svc = FinanceService(async_db_session)
    seed = await svc.get_or_create_category_from_hint("Food:Groceries")

    again = await svc.get_or_create_category_from_hint(
        "food:  groceries", owner_user_id=ALICE
    )

    assert again is not None and seed is not None
    assert again.id == seed.id


@pytest.mark.asyncio
async def test_an_alias_resolves_only_within_the_callers_scope(
    async_db_session: AsyncSession,
) -> None:
    svc = FinanceService(async_db_session)
    alices = await svc.get_or_create_category_from_hint(
        "Hobbies:Climbing", owner_user_id=ALICE
    )

    assert alices is not None
    assert (
        await svc.resolve_category_alias("Hobbies:Climbing", owner_user_id=ALICE)
        == alices.id
    )
    assert (
        await svc.resolve_category_alias("Hobbies:Climbing", owner_user_id=BOB)
        is None
    )


@pytest.mark.asyncio
async def test_standalone_keeps_shared_rows_and_unfiltered_reads(
    async_db_session: AsyncSession,
) -> None:
    svc = FinanceService(async_db_session)

    category = await svc.get_or_create_category_from_hint("Home:Repairs")

    assert category is not None
    assert category.owner_user_id is None
    assert "Home:Repairs" in await _names(svc, None)
