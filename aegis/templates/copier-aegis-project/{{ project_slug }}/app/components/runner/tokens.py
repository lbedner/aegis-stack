"""What a runner on another machine shows the app (``Authorization:
Bearer rnr_...``) to claim an owner's runs and post their results.

Minted by ``app.core.tokens``: the value is shown once, only its digest is
kept. A token belongs to one owner exactly (no owner: the operator's, on a
stack without auth); revoked, it resolves to nothing.
"""

from datetime import timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.core.tokens import digest, mint

from . import queries
from .models import RunnerToken

PREFIX = "rnr_"
# What a token starts with: ours, or meetings', which minted them before
# the runner was a component (found by their digest all the same).
PREFIXES = (PREFIX, "mrt_")
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
) -> tuple[RunnerToken, str]:
    """A new token for the owner's runner ``name``: its row, and its value
    (shown once)."""
    minted = mint(PREFIX)
    row = RunnerToken(
        owner_user_id=owner_user_id, name=name, digest=minted.digest, hint=minted.hint
    )
    db.add(row)
    await db.commit()
    return row, minted.value


async def resolve(db: AsyncSession, value: str) -> RunnerToken | None:
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


async def unanswered(db: AsyncSession) -> int:
    """How many asked runs no listening runner takes: none is running for
    their owner (a runner claims its token's owner's runs, or every
    owner's).

    ponytail: a runner on one step longer than ``LISTENING`` that posts
    nothing reads as gone while more waits; keep the token that claimed a
    run on it if that misleads.
    """
    return await queries.unanswered(db, utcnow() - LISTENING)


async def live(db: AsyncSession, owner_user_id: int | None) -> list[RunnerToken]:
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
