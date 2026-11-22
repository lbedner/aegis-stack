"""What a run's agent did, kept as its steps: each one its hooks post
(``note``, which also says what the run is doing now) and its session's
lines as its runner hears them (``hear``), each sort with ``MOST_STEPS``
of room; and read back in order (``steps``)."""

from typing import Any

from sqlalchemy import func, insert, literal
from sqlmodel import col, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.shared.queries import owner_filters

from .models import CLAIMED, MOST_STEPS, RunnerRun, RunnerStep
from .queries import held


async def note(
    db: AsyncSession, owner_user_id: int | None, session_id: str, activity: str | None
) -> None:
    """The latest run a runner took in the owner's session says it is doing
    ``activity`` (nothing, for None), as of now, and keeps it as a step
    while it has fewer than ``MOST_STEPS``: one still waiting to be
    claimed is not the one going. A session no run was taken in changes
    nothing. Two statements, each found in the database alone. The caller
    commits."""
    latest = select(func.max(col(RunnerRun.id))).where(
        RunnerRun.session_id == session_id,
        col(RunnerRun.claimed_at).is_not(None),
        *owner_filters(RunnerRun.owner_user_id, owner_user_id),
    )
    now = utcnow()
    noted = await db.exec(  # type: ignore[call-overload]
        update(RunnerRun)
        .where(col(RunnerRun.id) == latest.scalar_subquery())
        .values(activity=activity, activity_at=now)
        .returning(col(RunnerRun.id))
        .execution_options(synchronize_session=False)
    )
    run_id = noted.scalar_one_or_none()
    if run_id is None or not activity:
        return
    kept = _kept(run_id, hooked=True)
    room = select(literal(run_id), literal(now), literal(activity)).where(
        kept < MOST_STEPS
    )
    await db.exec(  # type: ignore[call-overload]
        insert(RunnerStep).from_select(["run_id", "at", "step"], room)
    )


def _kept(run_id: int, *, hooked: bool) -> Any:
    """How many steps a run keeps of one sort: its hooks' (no ``kind``), or
    its session's lines; each has ``MOST_STEPS`` of room, so a long session
    never crowds out its steps, nor its steps its session."""
    sort = (
        col(RunnerStep.kind).is_(None) if hooked else col(RunnerStep.kind).is_not(None)
    )
    return (
        select(func.count()).where(RunnerStep.run_id == run_id, sort).scalar_subquery()
    )


async def hear(
    db: AsyncSession,
    run_id: int,
    owner_user_id: int | None,
    runner: str,
    lines: list[tuple[str, str]],
) -> None:
    """``lines`` (a kind and its text) kept as the run's steps, after the
    ones before, if ``runner`` still holds it claimed, up to
    ``MOST_STEPS``: what room is left read in one statement, the lines
    written in one more. The caller commits."""
    kept = _kept(run_id, hooked=False)
    room = select(kept).where(
        *held(run_id, owner_user_id, runner), RunnerRun.status == CLAIMED
    )
    taken = (await db.exec(room)).first()  # type: ignore[call-overload]
    if taken is None:
        return
    now = utcnow()
    rows = [
        {"run_id": run_id, "at": now, "kind": kind, "step": text}
        for kind, text in lines[: max(MOST_STEPS - taken, 0)]
    ]
    if rows:
        await db.execute(insert(RunnerStep), rows)


async def steps(db: AsyncSession, run_id: int) -> list[RunnerStep]:
    """The steps a run's agent took, in the order it took them."""
    query = select(RunnerStep).where(RunnerStep.run_id == run_id)
    return list((await db.exec(query.order_by(col(RunnerStep.id)))).all())
