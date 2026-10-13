"""Each sign-in as the refresh-token table still keeps it, for Overseer's
Sessions page: when it began, each renewal, and whether it lives or how it
ended. Read-only; ``RefreshService`` writes the table.

A sign-in is one ``family_id``; rotation adds a row per renewal and revokes
the one before, so the newest row is the one in use. Ended sign-ins stay
readable for ``REFRESH_TOKEN_RETENTION_DAYS``, then the cleanup removes them.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import distinct, func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.refresh_token import RefreshToken, SessionEnd, SessionHistory


async def history(db: AsyncSession, user_id: int) -> list[SessionHistory]:
    """Every sign-in of ``user_id`` the table still keeps: the live ones,
    and those lately ended; the most recently used first. One query."""
    mine = select(RefreshToken).where(RefreshToken.user_id == user_id)
    return await _sign_ins(db, mine)


async def everyone(db: AsyncSession) -> list[SessionHistory]:
    """``history`` for every user at once, for the app's administrators.
    One query."""
    return await _sign_ins(db, select(RefreshToken))


async def one(db: AsyncSession, family_id: str) -> SessionHistory | None:
    """One sign-in, by its id; None if the table keeps nothing of it."""
    found = await _sign_ins(
        db, select(RefreshToken).where(RefreshToken.family_id == family_id)
    )
    return found[0] if found else None


async def live_counts(db: AsyncSession) -> dict[int, int]:
    """``{user_id: live sign-ins}`` for every user with one. One query."""
    sessions = func.count(distinct(RefreshToken.family_id))
    stmt = (
        select(RefreshToken.user_id, sessions)
        .where(RefreshToken.revoked_at.is_(None))  # type: ignore[union-attr]
        .where(RefreshToken.expires_at > utcnow())
        .group_by(RefreshToken.user_id)  # type: ignore[arg-type]
    )
    return {user_id: count for user_id, count in (await db.exec(stmt)).all()}


async def _sign_ins(db: AsyncSession, stmt: Any) -> list[SessionHistory]:
    """The sign-ins among the rows ``stmt`` selects, most recently used
    first."""
    families: dict[str, list[RefreshToken]] = {}
    ordered = stmt.order_by(RefreshToken.created_at)  # type: ignore[arg-type]
    for row in (await db.exec(ordered)).all():
        families.setdefault(row.family_id, []).append(row)
    now = utcnow()
    found = [_sign_in(tokens, now) for tokens in families.values()]
    return sorted(found, key=lambda h: h.last_used_at or h.signed_in, reverse=True)


def _sign_in(tokens: list[RefreshToken], now: datetime) -> SessionHistory:
    """One sign-in from its tokens, oldest first: the newest is the one in
    use, so it says whether the sign-in lives, and if not, whether it ran
    out or was revoked first."""
    first, last = tokens[0], tokens[-1]
    ended, ended_at = None, None
    if last.revoked_at is not None and last.revoked_at < last.expires_at:
        ended, ended_at = SessionEnd.REVOKED, last.revoked_at
    elif last.expires_at <= now or last.revoked_at is not None:
        ended, ended_at = SessionEnd.EXPIRED, last.expires_at
    return SessionHistory(
        id=last.family_id,
        user_id=last.user_id,
        source=last.source,
        user_agent=last.user_agent,
        ip=last.ip,
        signed_in=first.created_at,
        renewals=[token.created_at for token in tokens[1:]],
        last_used_at=last.last_used_at or last.created_at,
        expires_at=last.expires_at,
        ended=ended,
        ended_at=ended_at,
    )
