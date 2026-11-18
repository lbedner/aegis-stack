"""Asking a run about a subject, claiming it, finishing it.

A run is asked, then claimed by what runs it (a runner's name, or its
asker's own name for work it does in the app), then done or failed with
what it came back with. A claim is compare-and-set, so two runners never
take the same run. A claim never finished (its runner died, a restart
took the app's) fails once it is ``ABANDONED_AFTER`` old.

Each change (asked, taken, finished) is told in this process to whoever
watches here (``watching``), at once instead of on its next look; a task
started inside carries it. A run another process changes is not heard
here.
"""

from datetime import timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.hooks import Hook
from app.core.time import utcnow

from . import queries
from .models import DONE, FAILED, RunnerRun

# Twice a runner's own timeout (``client.Runner.timeout_seconds``): a run
# claimed longer ago than this is never coming back.
ABANDONED_AFTER = timedelta(minutes=30)
ABANDONED = "Its runner stopped before it answered."
STOPPED = "Told to stop."

_runs = Hook("runs")
watching = _runs.watching
# A run changed, to whoever is watching.
_changed = _runs.tell
about = queries.about
going = queries.going
answered = queries.answered
# These subjects' runs gone, or made another owner's, as their subjects
# are: the caller commits.
forget = queries.drop
hand_over = queries.hand_over


class RunNotFoundError(LookupError):
    """No run by that id is this owner's, claimed by this runner."""


async def ask(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    kind: str,
    subject_id: str,
    action: str,
    prompt: str,
    replacing: list[str] | None = None,
) -> RunnerRun:
    """A run of ``action`` about the subject, the owner's, asked: it waits
    to be claimed. It replaces the runs of ``action`` about ``replacing``
    (subjects of its kind), for an asker that keeps one answer."""
    if replacing:
        await queries.drop(db, kind, replacing, action)
    run = RunnerRun(
        owner_user_id=owner_user_id,
        subject_kind=kind,
        subject_id=subject_id,
        action=action,
        prompt=prompt,
    )
    db.add(run)
    await db.commit()
    _changed()
    return run


async def take(db: AsyncSession, run_id: int, runner: str) -> bool:
    """Claim the run for ``runner`` if it is still asked."""
    taken = await queries.take(db, run_id, runner)
    await db.commit()
    if taken:
        _changed()
    return taken


async def claim(
    db: AsyncSession, owner_user_id: int | None, actions: list[str], *, runner: str
) -> RunnerRun | None:
    """The oldest asked run of ``actions`` among the owner's, now claimed by
    ``runner``; None when there is none."""
    for _ in range(3):  # another runner may take the one picked first
        run_id = await queries.waiting(db, owner_user_id, actions)
        if run_id is None:
            return None
        if await take(db, run_id, runner):
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
) -> RunnerRun:
    """A run ``runner`` claimed, done (``ok``) or failed, with what it came
    back with. Only what claimed a run finishes it, and only while it is
    still claimed: another runner posting over it would lose the answer,
    and one stopped as its answer came back stays stopped."""
    status = DONE if ok else FAILED
    finished = await queries.finish(db, run_id, owner_user_id, runner, status, result)
    await db.commit()
    run = await queries.run(db, run_id) if finished else None
    if run is None:
        raise RunNotFoundError(run_id)
    _changed()
    return run


async def stop(
    db: AsyncSession, kind: str, subject_ids: list[str], result: str = STOPPED
) -> list[int]:
    """Every run still going about these subjects failed as ``result``
    (``STOPPED``), never finished: their ids."""
    if not subject_ids:
        return []
    stopped = await queries.fail_going(db, kind, subject_ids, result)
    await db.commit()
    _changed()
    return stopped


async def fail_abandoned(db: AsyncSession) -> int:
    """Fail every run claimed longer ago than ``ABANDONED_AFTER``: how many."""
    failed = await queries.fail_claimed_before(
        db, utcnow() - ABANDONED_AFTER, ABANDONED
    )
    await db.commit()
    return failed
