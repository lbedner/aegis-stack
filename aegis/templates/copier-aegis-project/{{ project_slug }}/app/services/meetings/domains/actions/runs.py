"""Asking an action of a moment, claiming the run, finishing it.

A run is asked, then claimed by what runs it (``app`` for an action that
runs in the app, a runner's name otherwise), then done or failed with what
it came back with. A claim is compare-and-set, so two runners never take
the same run. An action that runs in the app starts at once, in the
background; one that runs on a runner waits to be claimed. A claim never
finished (its runner died, a restart took the app's) fails once it is
``ABANDONED_AFTER`` old.
"""

from datetime import timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.concurrency import background
from app.core.db import get_async_session
from app.core.log import logger
from app.core.time import utcnow
from app.services.meetings.domains.actions import queries
from app.services.meetings.domains.actions.prompt import excerpt
from app.services.meetings.domains.actions.registry import Action, action_named
from app.services.meetings.models import (
    CLAIMED,
    DONE,
    FAILED,
    IN_THE_APP,
    Meeting,
    MeetingActionRun,
    MeetingMoment,
)

# Twice a runner's own timeout (``Runner.timeout_seconds``): a run claimed
# longer ago than this is never coming back.
ABANDONED_AFTER = timedelta(minutes=30)
ABANDONED = "Its runner stopped before it answered."


class ActionNotFoundError(LookupError):
    """No action by that name runs anywhere a run can be made for."""


class MomentNotFoundError(LookupError):
    """No moment by that id is this owner's."""


class RunNotFoundError(LookupError):
    """No run by that id is this owner's, claimed by this runner."""


async def ask(
    db: AsyncSession,
    moment_id: int,
    action_name: str,
    *,
    owner_user_id: int | None,
    meeting_id: int | None = None,
    together: list[MeetingMoment] | None = None,
) -> MeetingActionRun:
    """Ask ``action_name`` of the moment (in ``meeting_id``, when given), and
    of those said ``together`` with it after it (its burst): a run on the
    moment, with the prompt the action frames from them all. One that runs
    in the app starts at once. Asked again while the last is still going,
    it is that run; once that is back, the new run replaces it (one answer
    per action, over every moment of the card)."""
    action = action_named(action_name)
    if action is None or action.where == "browser":
        raise ActionNotFoundError(action_name)
    moment = await _moment(db, moment_id, owner_user_id, meeting_id)
    card = [moment, *(together or [])]
    ids = [m.id or 0 for m in card]
    going = await queries.going(db, ids, action.name)
    if going is not None:
        return going
    await queries.drop_runs(db, ids, action.name)
    run = MeetingActionRun(
        moment_id=moment_id,
        action=action.name,
        prompt=action.frame(await excerpt(db, card)),
    )
    db.add(run)
    await db.commit()
    if action.where == IN_THE_APP:
        background(_run_in_the_app(run.id or 0, action))
    return run


async def claim(
    db: AsyncSession, owner_user_id: int | None, actions: list[str], *, runner: str
) -> MeetingActionRun | None:
    """The oldest asked run of ``actions`` among the owner's meetings, now
    claimed by ``runner``; None when there is none."""
    for _ in range(3):  # another runner may take the one picked first
        run_id = await queries.waiting(db, owner_user_id, actions)
        if run_id is None:
            return None
        if await _take(db, run_id, runner):
            return await queries.run(db, run_id)
    return None


async def finish(
    db: AsyncSession,
    run_id: int,
    owner_user_id: int | None,
    result: str,
    *,
    ok: bool,
    runner: str,
) -> MeetingActionRun:
    """A run ``runner`` claimed, done (``ok``) or failed, with what it came
    back with. Only what claimed a run finishes it: another runner posting
    over it would lose the answer."""
    run = await queries.run(db, run_id, owner_user_id)
    if run is None or run.status != CLAIMED or run.runner != runner:
        raise RunNotFoundError(run_id)
    run.status, run.result, run.finished_at = (DONE if ok else FAILED), result, utcnow()
    db.add(run)
    await db.commit()
    return run


async def fail_abandoned(db: AsyncSession) -> int:
    """Fail every run claimed longer ago than ``ABANDONED_AFTER``: how many."""
    failed = await queries.fail_claimed_before(
        db, utcnow() - ABANDONED_AFTER, ABANDONED
    )
    await db.commit()
    return failed


async def _run_in_the_app(run_id: int, action: Action) -> None:
    """Claim the run as the app, run the action, and finish it with what it
    returned, or why it failed."""
    async with get_async_session() as db:
        if not await _take(db, run_id, IN_THE_APP):
            return
        run = await db.get_one(MeetingActionRun, run_id)
        moment = await db.get_one(MeetingMoment, run.moment_id)
        owner = (await db.get_one(Meeting, moment.meeting_id)).owner_user_id
        prompt = run.prompt
    try:
        if action.run is None:
            raise ActionNotFoundError(f"{action.name} has nothing to run in the app")
        result, ok = await action.run(prompt, owner), True
    except Exception as exc:
        logger.exception("Action failed", action=action.name, run_id=run_id)
        result, ok = str(exc) or type(exc).__name__, False
    async with get_async_session() as db:
        await finish(db, run_id, owner, result, ok=ok, runner=IN_THE_APP)


async def _take(db: AsyncSession, run_id: int, runner: str) -> bool:
    """Claim the run for ``runner`` if it is still asked."""
    taken = await queries.take(db, run_id, runner)
    await db.commit()
    return taken


async def _moment(
    db: AsyncSession,
    moment_id: int,
    owner_user_id: int | None,
    meeting_id: int | None = None,
) -> MeetingMoment:
    moment = await queries.moment(db, moment_id, owner_user_id, meeting_id)
    if moment is None:
        raise MomentNotFoundError(moment_id)
    return moment
