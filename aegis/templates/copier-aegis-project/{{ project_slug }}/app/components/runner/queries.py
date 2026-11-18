"""The reads (and the conditional writes) behind runs and runner tokens:
the oldest run waiting for a runner, taking a run if it is still asked,
failing runs claimed too long ago, a subject's runs, and tokens."""

from datetime import datetime
from typing import Any

from sqlalchemy import Select, Update
from sqlmodel import col, delete, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.shared.queries import owner_clause, owner_filters, visible_to

from .models import ASKED, CLAIMED, DONE, FAILED, GOING, RunnerRun, RunnerToken

# The subjects a read or a write is about: their ids, or a select of them
# (an asker's own rows, read in the same statement).
Subjects = list[str] | Select[tuple[str]]


def _matched(subject_ids: Subjects) -> dict[str, Any]:
    """How a write over these subjects finds the session's copies of what it
    changes: a select of subjects is matched in the database alone, where
    the default would first read which rows it is about to change (seen
    under the test database). Its caller holds no copies of them."""
    return {} if isinstance(subject_ids, list) else {"synchronize_session": False}


def _about(kind: str, subject_ids: Subjects) -> list[Any]:
    """Clauses keeping runs to these subjects of one kind."""
    return [RunnerRun.subject_kind == kind, col(RunnerRun.subject_id).in_(subject_ids)]


async def waiting(
    db: AsyncSession, owner_user_id: int | None, actions: list[str]
) -> int | None:
    """The oldest run of ``actions`` still asked among the owner's."""
    query = (
        select(RunnerRun.id)
        .where(
            *owner_filters(RunnerRun.owner_user_id, owner_user_id),
            RunnerRun.status == ASKED,
            col(RunnerRun.action).in_(actions),
        )
        .order_by(col(RunnerRun.asked_at), col(RunnerRun.id))
        .limit(1)
    )
    return (await db.exec(query)).first()


async def take(db: AsyncSession, run_id: int, runner: str) -> bool:
    """Claim the run for ``runner`` if it is still asked, in one
    statement, so only one runner ever takes it. The caller commits."""
    taken = await db.exec(  # type: ignore[call-overload]
        update(RunnerRun)
        .where(col(RunnerRun.id) == run_id, RunnerRun.status == ASKED)
        .values(status=CLAIMED, runner=runner, claimed_at=utcnow())
    )
    return bool(taken.rowcount)


async def finish(
    db: AsyncSession,
    run_id: int,
    owner_user_id: int | None,
    runner: str,
    status: str,
    result: str,
) -> bool:
    """Set the owner's run to ``status`` with ``result`` if ``runner`` still
    holds it claimed, in one statement, so a run stopped meanwhile is not
    answered after all. The caller commits."""
    finished = await db.exec(  # type: ignore[call-overload]
        _ending(status, result).where(
            col(RunnerRun.id) == run_id,
            *owner_filters(RunnerRun.owner_user_id, owner_user_id),
            RunnerRun.status == CLAIMED,
            RunnerRun.runner == runner,
        )
    )
    return bool(finished.rowcount)


async def fail_claimed_before(db: AsyncSession, cutoff: datetime, result: str) -> int:
    """Fail every run still claimed that was claimed before ``cutoff``, with
    ``result``: how many. The caller commits."""
    moved = await db.exec(  # type: ignore[call-overload]
        _ending(FAILED, result).where(
            RunnerRun.status == CLAIMED, col(RunnerRun.claimed_at) < cutoff
        )
    )
    return int(moved.rowcount or 0)


async def fail_going(
    db: AsyncSession, kind: str, subject_ids: list[str], result: str
) -> list[int]:
    """Fail every run about these subjects still asked or claimed, with
    ``result``: their ids. The caller commits."""
    moved = await db.exec(  # type: ignore[call-overload]
        _ending(FAILED, result)
        .where(*_about(kind, subject_ids), col(RunnerRun.status).in_(GOING))
        .returning(col(RunnerRun.id))
    )
    return [run_id for (run_id,) in moved.all()]


def _ending(status: str, result: str) -> Update:
    """Runs over as ``status`` with ``result``, as of now: the ones a
    ``where`` picks."""
    return update(RunnerRun).values(status=status, result=result, finished_at=utcnow())


async def run(db: AsyncSession, run_id: int) -> RunnerRun | None:
    """The run, read afresh."""
    query = (
        select(RunnerRun)
        .where(col(RunnerRun.id) == run_id)
        .execution_options(populate_existing=True)
    )
    return (await db.exec(query)).first()


async def about(db: AsyncSession, kind: str, subject_ids: list[str]) -> list[RunnerRun]:
    """These subjects' runs, oldest first."""
    query = (
        select(RunnerRun)
        .where(*_about(kind, subject_ids))
        .order_by(col(RunnerRun.asked_at), col(RunnerRun.id))
    )
    return list((await db.exec(query)).all())


async def going(
    db: AsyncSession, kind: str, subject_ids: list[str], action: str
) -> RunnerRun | None:
    """The run of ``action`` about any of these subjects still going, if
    any."""
    query = select(RunnerRun).where(
        *_about(kind, subject_ids),
        RunnerRun.action == action,
        col(RunnerRun.status).in_(GOING),
    )
    return (await db.exec(query)).first()


async def answered(
    db: AsyncSession, kind: str, subject_ids: list[str], action: str
) -> dict[str, tuple[str, str | None]]:
    """These subjects' runs of ``action`` that are over (done or failed):
    each one's status and result, by subject."""
    query = select(RunnerRun.subject_id, RunnerRun.status, RunnerRun.result).where(
        *_about(kind, subject_ids),
        RunnerRun.action == action,
        col(RunnerRun.status).in_((DONE, FAILED)),
    )
    return {s: (status, result) for s, status, result in (await db.exec(query)).all()}


async def drop(
    db: AsyncSession, kind: str, subject_ids: Subjects, action: str | None = None
) -> None:
    """Delete these subjects' runs (of ``action``, when given). The caller
    commits."""
    await db.exec(  # type: ignore[call-overload]
        delete(RunnerRun)
        .where(
            *_about(kind, subject_ids),
            *([RunnerRun.action == action] if action else []),
        )
        .execution_options(**_matched(subject_ids))
    )


async def hand_over(
    db: AsyncSession, kind: str, subject_ids: Subjects, owner_user_id: int | None
) -> None:
    """Make these subjects' runs ``owner_user_id``'s. The caller commits."""
    await db.exec(  # type: ignore[call-overload]
        update(RunnerRun)
        .where(*_about(kind, subject_ids))
        .values(owner_user_id=owner_user_id)
        .execution_options(**_matched(subject_ids))
    )


async def used_since(
    db: AsyncSession, owner_user_id: int | None, since: datetime
) -> bool:
    """Whether a runner token that claims the owner's runs (theirs, or one
    for every owner) was used since ``since``."""
    query = select(RunnerToken.id).where(
        col(RunnerToken.revoked_at).is_(None),
        col(RunnerToken.last_used_at) >= since,
        *visible_to(RunnerToken.owner_user_id, owner_user_id),
    )
    return (await db.exec(query.limit(1))).first() is not None


async def live_token(
    db: AsyncSession,
    *,
    digest: str | None = None,
    token_id: int | None = None,
    owner_user_id: int | None = None,
) -> RunnerToken | None:
    """The token not revoked with ``digest`` (any owner's), or with id
    ``token_id`` among the owner's."""
    query = select(RunnerToken).where(col(RunnerToken.revoked_at).is_(None))
    if digest is not None:
        query = query.where(RunnerToken.digest == digest)
    else:
        query = query.where(
            RunnerToken.id == token_id,
            owner_clause(RunnerToken.owner_user_id, owner_user_id),
        )
    return (await db.exec(query)).first()


async def live_tokens(db: AsyncSession, owner_user_id: int | None) -> list[RunnerToken]:
    """The owner's tokens not revoked, newest first."""
    query = (
        select(RunnerToken)
        .where(
            owner_clause(RunnerToken.owner_user_id, owner_user_id),
            col(RunnerToken.revoked_at).is_(None),
        )
        .order_by(col(RunnerToken.created_at).desc())
    )
    return list((await db.exec(query)).all())
