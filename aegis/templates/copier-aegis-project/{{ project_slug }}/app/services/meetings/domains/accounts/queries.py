"""The reads behind the agents: every agent, which meetings each is in
now, which have a picture (and the picture), and the writes a read alone
would not do: dropping a picture, and the one backfill that hands the
meetings sent before agents to the first."""

from datetime import datetime

from sqlalchemy import delete, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.models import AgentImage, BotAccount, Meeting


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


async def with_images(db: AsyncSession, account_ids: list[int]) -> dict[int, datetime]:
    """Those of ``account_ids`` with a picture kept, and when each changed."""
    query = select(AgentImage.account_id, AgentImage.updated_at).where(
        col(AgentImage.account_id).in_(account_ids)
    )
    return dict((await db.exec(query)).all())


async def image_named(db: AsyncSession, name: str) -> AgentImage | None:
    """The picture of the agent called ``name``, if it has one."""
    query = (
        select(AgentImage)
        .join(BotAccount, col(BotAccount.id) == col(AgentImage.account_id))
        .where(BotAccount.name == name)
    )
    return (await db.exec(query)).first()


async def drop_image(db: AsyncSession, account_id: int) -> None:
    """The agent's picture gone, without reading it first."""
    await db.exec(  # type: ignore[call-overload]
        delete(AgentImage).where(col(AgentImage.account_id) == account_id)
    )
