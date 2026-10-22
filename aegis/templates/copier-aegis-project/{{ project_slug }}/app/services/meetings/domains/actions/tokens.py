"""What a runner on another machine shows the app (``Authorization:
Bearer mrt_...``) to claim an owner's runs and post their results.

Minted by ``app.core.tokens``: the value is shown once, only its digest is
kept. A token belongs to one owner exactly (no owner: the operator's, on a
stack without auth); revoked, it resolves to nothing.
"""

from datetime import timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.core.tokens import digest, mint
from app.services.meetings.domains.actions import queries
from app.services.meetings.models import MeetingRunnerToken

PREFIX = "mrt_"
# How often a token's use is noted: a runner polls every few seconds, and
# each note is a write.
NOTED_EVERY = timedelta(minutes=1)


# A runner polls every few seconds and its token's use is noted once a
# minute: unseen for longer than this, none is running.
LISTENING = 2 * NOTED_EVERY


class RunnerTokenNotFoundError(LookupError):
    """No live runner token by that id is this owner's."""


async def create(
    db: AsyncSession, owner_user_id: int | None, name: str
) -> tuple[MeetingRunnerToken, str]:
    """A new token for the owner's runner ``name``: its row, and its value
    (shown once)."""
    minted = mint(PREFIX)
    row = MeetingRunnerToken(
        owner_user_id=owner_user_id, name=name, digest=minted.digest, hint=minted.hint
    )
    db.add(row)
    await db.commit()
    return row, minted.value


async def resolve(db: AsyncSession, value: str) -> MeetingRunnerToken | None:
    """The live token ``value`` is, noting its use (once ``NOTED_EVERY``);
    None if it is unknown or revoked."""
    row = await queries.live_token(db, digest=digest(value))
    if row is None:
        return None
    now = utcnow()
    if row.last_used_at is None or now - row.last_used_at >= NOTED_EVERY:
        row.last_used_at = now
        db.add(row)
        await db.commit()
    return row


async def listening(db: AsyncSession, owner_user_id: int | None) -> bool:
    """Whether a runner that claims the owner's runs is running now."""
    return await queries.used_since(db, owner_user_id, utcnow() - LISTENING)


async def live(db: AsyncSession, owner_user_id: int | None) -> list[MeetingRunnerToken]:
    """The owner's tokens not revoked, newest first."""
    return await queries.live_tokens(db, owner_user_id)


async def revoke(db: AsyncSession, token_id: int, owner_user_id: int | None) -> None:
    """Revoke one of the owner's tokens: ``RunnerTokenNotFoundError`` if it
    is not theirs or is already revoked."""
    row = await queries.live_token(db, token_id=token_id, owner_user_id=owner_user_id)
    if row is None:
        raise RunnerTokenNotFoundError(f"No live runner token {token_id}")
    row.revoked_at = utcnow()
    db.add(row)
    await db.commit()
