"""The reads behind the agents: every agent, which meetings each is in
now, and the one backfill that hands the meetings sent before agents to
the first."""

from sqlalchemy import update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.models import BotAccount, Meeting


async def every_account(db: AsyncSession) -> list[BotAccount]:
    """Every agent, oldest (the default) first."""
    return list((await db.exec(select(BotAccount).order_by(col(BotAccount.id)))).all())


async def meetings_in(
    db: AsyncSession, statuses: tuple[str, ...]
) -> list[tuple[int | None, int]]:
    """``(account_id, meeting_id)`` of every meeting in one of ``statuses``."""
    query = (
        select(Meeting.account_id, Meeting.id)
        .where(col(Meeting.status).in_(statuses))
        .order_by(col(Meeting.id))
    )
    return list((await db.exec(query)).all())


async def give_unsent_meetings(db: AsyncSession, account_id: int) -> None:
    """Every meeting sent before agents becomes ``account_id``'s."""
    await db.exec(  # type: ignore[call-overload]
        update(Meeting)
        .where(col(Meeting.account_id).is_(None))
        .values(account_id=account_id)
    )
