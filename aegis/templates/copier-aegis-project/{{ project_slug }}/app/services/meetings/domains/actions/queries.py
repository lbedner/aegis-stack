"""The reads (and the conditional writes) behind actions: the oldest run
waiting for a runner, taking a run if it is still asked, failing runs
claimed too long ago, a run or a moment as one owner may see it, and
runner tokens."""

from datetime import datetime
from typing import Any

from sqlmodel import col, delete, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.meetings.models import (
    ASKED,
    CLAIMED,
    FAILED,
    GOING,
    Meeting,
    MeetingActionRun,
    MeetingMoment,
    MeetingRunnerToken,
)
from app.services.shared.queries import owner_clause, owner_filters, visible_to


def _owned(query: Any, owner_user_id: int | None) -> Any:
    """``query`` over moments (or what joins them), kept to the owner's
    meetings."""
    return query.join(Meeting, col(Meeting.id) == MeetingMoment.meeting_id).where(
        *owner_filters(Meeting.owner_user_id, owner_user_id)
    )


def _with_moment(query: Any) -> Any:
    """``query`` over runs, joined to their moments."""
    return query.join(
        MeetingMoment, col(MeetingMoment.id) == MeetingActionRun.moment_id
    )


async def waiting(
    db: AsyncSession, owner_user_id: int | None, actions: list[str]
) -> int | None:
    """The oldest run of ``actions`` still asked among the owner's
    meetings."""
    query = (
        _owned(_with_moment(select(MeetingActionRun.id)), owner_user_id)
        .where(
            MeetingActionRun.status == ASKED,
            col(MeetingActionRun.action).in_(actions),
        )
        .order_by(col(MeetingActionRun.asked_at), col(MeetingActionRun.id))
        .limit(1)
    )
    return (await db.exec(query)).first()


async def take(db: AsyncSession, run_id: int, runner: str) -> bool:
    """Claim the run for ``runner`` if it is still asked, in one
    statement, so only one runner ever takes it. The caller commits."""
    taken = await db.exec(  # type: ignore[call-overload]
        update(MeetingActionRun)
        .where(col(MeetingActionRun.id) == run_id, MeetingActionRun.status == ASKED)
        .values(status=CLAIMED, runner=runner, claimed_at=utcnow())
    )
    return bool(taken.rowcount)


async def fail_claimed_before(db: AsyncSession, cutoff: datetime, result: str) -> int:
    """Fail every run still claimed that was claimed before ``cutoff``, with
    ``result``: how many. The caller commits."""
    moved = await db.exec(  # type: ignore[call-overload]
        update(MeetingActionRun)
        .where(
            MeetingActionRun.status == CLAIMED,
            col(MeetingActionRun.claimed_at) < cutoff,
        )
        .values(status=FAILED, result=result, finished_at=utcnow())
    )
    return int(moved.rowcount or 0)


async def run(
    db: AsyncSession, run_id: int, owner_user_id: int | None = None
) -> MeetingActionRun | None:
    """The run, if it is in one of the owner's meetings, read afresh."""
    query = (
        _owned(_with_moment(select(MeetingActionRun)), owner_user_id)
        .where(col(MeetingActionRun.id) == run_id)
        .execution_options(populate_existing=True)
    )
    return (await db.exec(query)).first()


async def moment(
    db: AsyncSession,
    moment_id: int,
    owner_user_id: int | None,
    meeting_id: int | None = None,
) -> MeetingMoment | None:
    """The moment, if it is in one of the owner's meetings (``meeting_id``,
    when given)."""
    query = _owned(select(MeetingMoment), owner_user_id).where(
        col(MeetingMoment.id) == moment_id,
        *([MeetingMoment.meeting_id == meeting_id] if meeting_id else []),
    )
    return (await db.exec(query)).first()


async def going(
    db: AsyncSession, moment_ids: list[int], action: str
) -> MeetingActionRun | None:
    """The run of ``action`` on any of these moments (a card's) still
    going, if any."""
    query = select(MeetingActionRun).where(
        col(MeetingActionRun.moment_id).in_(moment_ids),
        MeetingActionRun.action == action,
        col(MeetingActionRun.status).in_(GOING),
    )
    return (await db.exec(query)).first()


async def going_in(db: AsyncSession, meeting_id: int) -> set[str]:
    """The statuses of the meeting's runs not yet done (asked, claimed)."""
    query = _with_moment(select(MeetingActionRun.status)).where(
        MeetingMoment.meeting_id == meeting_id,
        col(MeetingActionRun.status).in_(GOING),
    )
    return set((await db.exec(query.distinct())).all())


async def drop_runs(db: AsyncSession, moment_ids: list[int], action: str) -> None:
    """Delete these moments' (a card's) runs of ``action``: a new one
    replaces them. The caller commits."""
    await db.exec(  # type: ignore[call-overload]
        delete(MeetingActionRun).where(
            col(MeetingActionRun.moment_id).in_(moment_ids),
            MeetingActionRun.action == action,
        )
    )


async def used_since(
    db: AsyncSession, owner_user_id: int | None, since: datetime
) -> bool:
    """Whether a runner token that claims the owner's runs (theirs, or one
    for every owner) was used since ``since``."""
    query = select(MeetingRunnerToken.id).where(
        col(MeetingRunnerToken.revoked_at).is_(None),
        col(MeetingRunnerToken.last_used_at) >= since,
        *visible_to(MeetingRunnerToken.owner_user_id, owner_user_id),
    )
    return (await db.exec(query.limit(1))).first() is not None


async def live_token(
    db: AsyncSession,
    *,
    digest: str | None = None,
    token_id: int | None = None,
    owner_user_id: int | None = None,
) -> MeetingRunnerToken | None:
    """The token not revoked with ``digest`` (any owner's), or with id
    ``token_id`` among the owner's."""
    query = select(MeetingRunnerToken).where(
        col(MeetingRunnerToken.revoked_at).is_(None)
    )
    if digest is not None:
        query = query.where(MeetingRunnerToken.digest == digest)
    else:
        query = query.where(
            MeetingRunnerToken.id == token_id,
            owner_clause(MeetingRunnerToken.owner_user_id, owner_user_id),
        )
    return (await db.exec(query)).first()


async def live_tokens(
    db: AsyncSession, owner_user_id: int | None
) -> list[MeetingRunnerToken]:
    """The owner's tokens not revoked, newest first."""
    query = (
        select(MeetingRunnerToken)
        .where(
            owner_clause(MeetingRunnerToken.owner_user_id, owner_user_id),
            col(MeetingRunnerToken.revoked_at).is_(None),
        )
        .order_by(col(MeetingRunnerToken.created_at).desc())
    )
    return list((await db.exec(query)).all())
