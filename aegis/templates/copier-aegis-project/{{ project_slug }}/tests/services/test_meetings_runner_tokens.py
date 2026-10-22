"""Runner tokens: what a runner on another machine shows the app to claim
an owner's runs and post their results. The value is shown once; only its
digest is kept, with a hint to tell tokens apart."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.actions import tokens


async def test_a_token_is_shown_once_and_resolves_to_its_owner(
    async_db_session: AsyncSession,
) -> None:
    row, value = await tokens.create(async_db_session, None, "laptop")

    assert value.startswith(tokens.PREFIX)
    assert value not in (row.digest, row.hint)
    assert row.hint == value[: len(tokens.PREFIX) + 4]
    found = await tokens.resolve(async_db_session, value)
    assert found is not None and found.id == row.id and found.last_used_at is not None


async def test_a_polling_runner_is_noted_once_a_minute_not_every_poll(
    async_db_session: AsyncSession,
) -> None:
    """A runner asks every few seconds: noting each would be a write each
    time, on the lock the bot's captions take too."""
    row, value = await tokens.create(async_db_session, None, "laptop")
    first = (await tokens.resolve(async_db_session, value)).last_used_at  # type: ignore[union-attr]

    again = await tokens.resolve(async_db_session, value)
    assert again is not None and again.last_used_at == first

    again.last_used_at -= tokens.NOTED_EVERY  # type: ignore[operator]
    later = await tokens.resolve(async_db_session, value)
    assert later is not None and later.last_used_at > first  # type: ignore[operator]


async def test_an_unknown_or_revoked_token_resolves_to_nothing(
    async_db_session: AsyncSession,
) -> None:
    row, value = await tokens.create(async_db_session, None, "laptop")

    assert await tokens.resolve(async_db_session, value + "x") is None
    await tokens.revoke(async_db_session, row.id or 0, None)
    assert await tokens.resolve(async_db_session, value) is None
    with pytest.raises(tokens.RunnerTokenNotFoundError):
        await tokens.revoke(async_db_session, row.id or 0, None)


async def test_an_owner_lists_and_revokes_only_their_own(
    async_db_session: AsyncSession,
) -> None:
    from tests._meetings import someone_else

    theirs = await someone_else(async_db_session)
    mine, _ = await tokens.create(async_db_session, None, "laptop")
    other, _ = await tokens.create(async_db_session, theirs, "desk")

    assert [t.name for t in await tokens.live(async_db_session, None)] == ["laptop"]
    with pytest.raises(tokens.RunnerTokenNotFoundError):
        await tokens.revoke(async_db_session, other.id or 0, None)
    await tokens.revoke(async_db_session, mine.id or 0, None)
    assert await tokens.live(async_db_session, None) == []
