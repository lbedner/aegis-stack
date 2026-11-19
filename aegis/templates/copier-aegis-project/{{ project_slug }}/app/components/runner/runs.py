"""Asking a run about a subject, claiming it, finishing it.

A run is asked, then claimed by what runs it (a runner's name, or its
asker's own name for work it does in the app), then done or failed with
what it came back with. A claim is compare-and-set, so two runners never
take the same run. A claim never finished (its runner died, a restart
took the app's) fails once it is overdue: twice what its runner gives a
command, ``ABANDONED_AFTER`` where it said nothing.

A run that is work rather than one answer is asked on a ``branch`` and in
a session (``new_session``): its runner keeps the worktree, and a later
run of the same session resumes it (``resumes``).

Each change (asked, taken, finished) is told in this process to whoever
watches here (``watching``), at once instead of on its next look; a task
started inside carries it. A run another process changes is not heard
here.
"""

from datetime import timedelta
from uuid import uuid4

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.hooks import Hook
from app.core.time import utcnow

from . import queries
from .models import DONE, FAILED, MOST_ACTIVITY, MOST_TITLE, RunnerRun
from .protocol import MOST_AGENT, TIMEOUT_SECONDS, kept

# How long a claimed run is waited for where its runner gave no timeout
# (the app's own, or a runner from before they did): twice a runner's
# default, as one that did is waited for twice its own.
ABANDONED_AFTER = timedelta(seconds=2 * TIMEOUT_SECONDS)
ABANDONED = "Its runner stopped before it answered."
STOPPED = "Told to stop."

_runs = Hook("runs")
watching = _runs.watching
# A run changed, to whoever is watching.
_changed = _runs.tell
about = queries.about
going = queries.going
answered = queries.answered
latest = queries.latest
tally = queries.tally
Tally = queries.Tally
# One run, read afresh.
one = queries.run
# These subjects' runs gone, or made another owner's, as their subjects
# are: the caller commits.
forget = queries.drop
hand_over = queries.hand_over


class RunNotFoundError(LookupError):
    """No run by that id is this owner's, claimed by this runner."""


def new_session() -> str:
    """An id for an agent's session, chosen before the agent starts: what a
    run is asked in, and what picks it up from a terminal."""
    return str(uuid4())


async def resumes(db: AsyncSession, run: RunnerRun) -> bool:
    """Whether the run should try to continue its session rather than
    start it: a runner took an earlier run of the session, so the agent may
    have begun it. A session cannot be started twice; one the agent never
    began refuses to resume, and its runner starts it instead."""
    return await queries.taken_in_session(db, run.id or 0)


def _cut(words: str | None, most: int = MOST_TITLE) -> str | None:
    """Words cut to what a run keeps of them (a title, a source; a step,
    to ``MOST_ACTIVITY``), None for none."""
    return words[:most] if words else None


async def ask(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    kind: str,
    subject_id: str,
    action: str,
    prompt: str,
    title: str | None = None,
    source: str | None = None,
    replacing: list[str] | None = None,
    branch: str | None = None,
    session_id: str | None = None,
) -> RunnerRun:
    """A run of ``action`` about the subject, the owner's, asked: it waits
    to be claimed. It replaces the runs of ``action`` about ``replacing``
    (subjects of its kind), for an asker that keeps one answer. ``title``
    is what a reader calls it and ``source`` where it was asked, each cut
    to what a run keeps. Work is
    asked on a ``branch`` (its worktree stays) and in a session
    (``new_session``, or an earlier run's, to resume it)."""
    if replacing:
        await queries.drop(db, kind, replacing, action)
    run = RunnerRun(
        owner_user_id=owner_user_id,
        subject_kind=kind,
        subject_id=subject_id,
        action=action,
        title=_cut(title),
        source=_cut(source),
        prompt=prompt,
        branch=branch,
        session_id=session_id,
    )
    db.add(run)
    await db.commit()
    _changed()
    return run


async def take(
    db: AsyncSession,
    run_id: int,
    runner: str,
    *,
    timeout: float | None = None,
    worktrees: str | None = None,
    agent: str | None = None,
) -> bool:
    """Claim the run for ``runner`` if it is still asked. What the runner
    says of itself goes on the run: how long it gives a command
    (``timeout``, seconds), so the run is waited for twice that, where
    it keeps a branch's worktree (``worktrees``), so a run on a branch says
    where its work is before it is back, and which ``agent`` it runs (cut
    to what a run keeps). A run asked in no session is given one, so what
    its agent says it is doing finds it (``note``)."""
    wait = timedelta(seconds=2 * timeout) if timeout else ABANDONED_AFTER
    taken = await queries.take(
        db,
        run_id,
        runner,
        overdue_at=utcnow() + wait,
        session_id=new_session(),
        worktrees=worktrees,
        agent=_cut(agent, MOST_AGENT),
    )
    await db.commit()
    if taken:
        _changed()
    return taken


async def claim(
    db: AsyncSession,
    owner_user_id: int | None,
    actions: list[str],
    *,
    runner: str,
    timeout: float | None = None,
    worktrees: str | None = None,
    agent: str | None = None,
) -> RunnerRun | None:
    """The oldest asked run of ``actions`` among the owner's, now claimed by
    ``runner`` (``take``); None when there is none."""
    for _ in range(3):  # another runner may take the one picked first
        run_id = await queries.waiting(db, owner_user_id, actions)
        if run_id is None:
            return None
        taken = await take(
            db, run_id, runner, timeout=timeout, worktrees=worktrees, agent=agent
        )
        if taken:
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
    cost: float | None = None,
    worktree: str | None = None,
) -> RunnerRun:
    """A run ``runner`` claimed, done (``ok``) or failed, with what it came
    back with and where its work is kept. ``cost`` is what the agent says
    its session has cost so far; the run keeps what it added to that (what
    the session's other runs have not already kept), so a session's cost is
    the sum of its runs'. Only what claimed a run
    finishes it, and only while it is still claimed: another runner posting
    over it would lose the answer, and one stopped as its answer came back
    stays stopped."""
    status = DONE if ok else FAILED
    if cost is not None:
        cost = max(cost - await queries.cost_of_session(db, run_id), 0.0)
    finished = await queries.finish(
        db,
        run_id,
        owner_user_id,
        runner,
        status,
        kept(result, ok),
        cost=cost,
        worktree=worktree,
    )
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


async def note(
    db: AsyncSession, owner_user_id: int | None, session_id: str, activity: str
) -> None:
    """What the agent in the owner's session says it is doing now (cut to
    what a run keeps; nothing, once it ended its turn), on the latest run
    a runner took in the session: the one going, or the one a terminal
    picked up."""
    doing = _cut(activity, MOST_ACTIVITY)
    await queries.note(db, owner_user_id, session_id, doing)
    await db.commit()


async def fail_abandoned(db: AsyncSession) -> int:
    """Fail every run still claimed past when it was due back: how many."""
    now = utcnow()
    failed = await queries.fail_overdue(db, now, now - ABANDONED_AFTER, ABANDONED)
    await db.commit()
    return failed
