"""Reads over sign-in sessions that count rather than list: what the
auth service's aggregates are made of."""

from datetime import datetime

from sqlalchemy import distinct, func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.refresh_token import RefreshToken
from app.services.shared.queries import day_of, within


async def by_day(
    db: AsyncSession, since: datetime | None
) -> tuple[dict[str, int], dict[str, int]]:
    """Sign-ins (sessions begun) and users active (a token issued or
    renewed) each day since ``since``, as far back as tokens are kept: two
    GROUP BYs, counts only."""
    begun = select(func.min(RefreshToken.created_at).label("at"))
    if since is not None:  # only the sessions with a token in the window
        touched = select(RefreshToken.family_id).where(RefreshToken.created_at >= since)
        begun = begun.where(RefreshToken.family_id.in_(touched))  # type: ignore[attr-defined]
    begun = begun.group_by(RefreshToken.family_id).subquery()  # type: ignore[arg-type]
    signed_day = func.date(begun.c.at)
    signed = select(signed_day, func.count()).where(*within(begun.c.at, since, None))
    day = func.date(RefreshToken.created_at)
    active = (
        select(day, func.count(distinct(RefreshToken.user_id)))
        .where(*within(RefreshToken.created_at, since, None))
        .group_by(day)
    )
    sign_ins = (await db.exec(signed.group_by(signed_day))).all()
    users = (await db.exec(active)).all()
    return (
        {day_of(on): int(n) for on, n in sign_ins},
        {day_of(on): int(n) for on, n in users},
    )
