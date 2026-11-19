"""The reads (and the conditional writes) behind runs and runner tokens:
the oldest run waiting for a runner, taking a run if it is still asked,
failing runs claimed too long ago, a subject's runs, and tokens."""

from datetime import datetime
from typing import Any, NamedTuple

from sqlalchemy import Select, Update, func, literal
from sqlalchemy.orm import defer
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


async def take(
    db: AsyncSession,
    run_id: int,
    runner: str,
    *,
    overdue_at: datetime,
    session_id: str,
    worktrees: str | None = None,
    agent: str | None = None,
) -> bool:
    """Claim the run for ``runner`` if it is still asked, in one
    statement, so only one runner ever takes it: overdue at ``overdue_at``,
    in ``session_id`` where it was asked in none, and, for a run on a
    branch taken by a runner that keeps worktrees under ``worktrees``,
    saying where its work will be. The caller commits."""
    placed = {"worktree": literal(f"{worktrees}/") + col(RunnerRun.branch)}
    taken = await db.exec(  # type: ignore[call-overload]
        update(RunnerRun)
        .where(col(RunnerRun.id) == run_id, RunnerRun.status == ASKED)
        .values(
            status=CLAIMED,
            runner=runner,
            agent=agent,
            claimed_at=utcnow(),
            overdue_at=overdue_at,
            session_id=func.coalesce(col(RunnerRun.session_id), session_id),
            **(placed if worktrees else {}),
        )
    )
    return bool(taken.rowcount)


async def finish(
    db: AsyncSession,
    run_id: int,
    owner_user_id: int | None,
    runner: str,
    status: str,
    result: str,
    *,
    cost: float | None,
    worktree: str | None,
) -> bool:
    """Set the owner's run to ``status`` with ``result``, what it cost and
    where its work is, if ``runner`` still holds it claimed, in one
    statement, so a run stopped meanwhile is not answered after all (and
    keeps the worktree it was claimed with). The caller commits."""
    finished = await db.exec(  # type: ignore[call-overload]
        _ending(status, result)
        .values(cost=cost, worktree=worktree)
        .where(
            col(RunnerRun.id) == run_id,
            *owner_filters(RunnerRun.owner_user_id, owner_user_id),
            RunnerRun.status == CLAIMED,
            RunnerRun.runner == runner,
        )
    )
    return bool(finished.rowcount)


async def note(
    db: AsyncSession, owner_user_id: int | None, session_id: str, activity: str | None
) -> None:
    """The latest run a runner took in the owner's session says it is doing
    ``activity`` (nothing, for None), as of now: one still waiting to be
    claimed is not the one going. A session no run was taken in changes
    nothing. One statement, found in the database alone (``_matched``).
    The caller commits."""
    latest = select(func.max(col(RunnerRun.id))).where(
        RunnerRun.session_id == session_id,
        col(RunnerRun.claimed_at).is_not(None),
        *owner_filters(RunnerRun.owner_user_id, owner_user_id),
    )
    await db.exec(  # type: ignore[call-overload]
        update(RunnerRun)
        .where(col(RunnerRun.id) == latest.scalar_subquery())
        .values(activity=activity, activity_at=utcnow())
        .execution_options(synchronize_session=False)
    )


def _others_in_session(run_id: int) -> list[Any]:
    """Clauses keeping runs to the other runs of this run's session: none
    for a run in no session."""
    its = (
        select(RunnerRun.session_id)
        .where(col(RunnerRun.id) == run_id)
        .scalar_subquery()
    )
    return [col(RunnerRun.session_id) == its, col(RunnerRun.id) != run_id]


async def taken_in_session(db: AsyncSession, run_id: int) -> bool:
    """Whether a runner took an earlier run of this run's session: the
    agent may have begun the session then."""
    query = select(RunnerRun.id).where(
        *_others_in_session(run_id),
        col(RunnerRun.id) < run_id,
        col(RunnerRun.claimed_at).is_not(None),
    )
    return (await db.exec(query.limit(1))).first() is not None


async def cost_of_session(db: AsyncSession, run_id: int) -> float:
    """What the other runs of this run's session have cost, together:
    every one that answered before it, whichever was asked first."""
    query = select(func.coalesce(func.sum(col(RunnerRun.cost)), 0.0)).where(
        *_others_in_session(run_id)
    )
    return float((await db.exec(query)).one())


async def fail_overdue(
    db: AsyncSession, now: datetime, claimed_before: datetime, result: str
) -> int:
    """Fail every run still claimed past when it was due back, with
    ``result``: how many. One claimed before runs said when (no
    ``overdue_at``) is due once it was claimed before ``claimed_before``.
    The caller commits."""
    late = col(RunnerRun.overdue_at) < now
    undated = col(RunnerRun.overdue_at).is_(None) & (
        col(RunnerRun.claimed_at) < claimed_before
    )
    moved = await db.exec(  # type: ignore[call-overload]
        _ending(FAILED, result).where(RunnerRun.status == CLAIMED, late | undated)
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


async def standing(db: AsyncSession) -> dict[str, int]:
    """How many runs are still going at each status, every owner's."""
    query = (
        select(RunnerRun.status, func.count())
        .where(col(RunnerRun.status).in_(GOING))
        .group_by(col(RunnerRun.status))
    )
    return {status: count for status, count in (await db.exec(query)).all()}


async def unanswered(db: AsyncSession, since: datetime) -> int:
    """How many asked runs no runner is about to take: no token that claims
    them (their owner's, or one for every owner) was used since ``since``."""
    takes = col(RunnerToken.owner_user_id).is_(None) | (
        col(RunnerToken.owner_user_id) == col(RunnerRun.owner_user_id)
    )
    listening = select(RunnerToken.id).where(
        col(RunnerToken.revoked_at).is_(None),
        col(RunnerToken.last_used_at) >= since,
        takes,
    )
    query = (
        select(func.count())
        .select_from(RunnerRun)
        .where(RunnerRun.status == ASKED, ~listening.exists())
    )
    return (await db.exec(query)).one()


class Tally(NamedTuple):
    """How one action's runs stand: what waits and what a runner has,
    whenever asked; what failed and what was spent since a time."""

    action: str
    waiting: int
    running: int
    failed: int
    cost: float


async def tally(db: AsyncSession, since: datetime) -> list[Tally]:
    """Every action's ``Tally``, every owner's runs, by action.

    Of the runs still kept: one replaced by a later ask of the same thing
    (``drop``) takes what it cost with it, and one stopped or overdue never
    said what it cost. So what was spent is at least this.

    ponytail: one pass over every run, on each load of the page that shows
    it (a row opened is one). Once that is felt: keep to the runs going or
    finished since ``since`` (an index on ``finished_at``), and an index on
    ``(action, id)`` for the actions' names and ``latest`` kept to one.
    """
    lately = col(RunnerRun.finished_at) >= since
    query = (
        select(
            RunnerRun.action,
            func.count().filter(RunnerRun.status == ASKED),
            func.count().filter(RunnerRun.status == CLAIMED),
            func.count().filter(RunnerRun.status == FAILED, lately),
            func.coalesce(func.sum(col(RunnerRun.cost)).filter(lately), 0.0),
        )
        .group_by(col(RunnerRun.action))
        .order_by(col(RunnerRun.action))
    )
    return [Tally(*row) for row in (await db.exec(query)).all()]


async def latest(
    db: AsyncSession, limit: int, action: str | None = None
) -> list[tuple[RunnerRun, bool]]:
    """The newest runs (of ``action``, when given), every owner's, newest
    first and read afresh: all but what was asked and what came back,
    which a list does not show, each with whether anything came back."""
    # Compared, not measured: a long result is not read to know it is one.
    back = col(RunnerRun.result) != ""
    query = (
        select(RunnerRun, back)
        .where(*([RunnerRun.action == action] if action else []))
        .options(defer(RunnerRun.prompt), defer(RunnerRun.result))  # type: ignore[arg-type]
        .order_by(col(RunnerRun.id).desc())
        .limit(limit)
        .execution_options(populate_existing=True)
    )
    return [(run, bool(said)) for run, said in (await db.exec(query)).all()]


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
