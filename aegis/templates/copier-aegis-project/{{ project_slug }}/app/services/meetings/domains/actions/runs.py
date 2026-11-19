"""Asking an action of a moment, and running the ones the app answers.

A run is the runner component's (``app.components.runner.runs``): asked
about a moment, claimed by what runs it (``app`` for an action that runs
in the app, a runner's name otherwise), then done or failed with what it
came back with. An action that runs in the app starts at once, in the
background; one that runs on a runner waits to be claimed.
"""

import asyncio
from datetime import datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.runner import runs
from app.components.runner.models import MOST_TITLE, RunnerRun
from app.components.runner.runs import STOPPED, RunNotFoundError
from app.core.concurrency import background
from app.core.db import get_async_session
from app.core.log import logger
from app.services.meetings.domains.actions import queries
from app.services.meetings.domains.actions.live import aloud, asking
from app.services.meetings.domains.actions.prompt import excerpt
from app.services.meetings.domains.actions.registry import Action, action_named
from app.services.meetings.models import (
    IN_THE_APP,
    MOMENT,
    MeetingMoment,
    moment_of,
    subjects,
)

# Each run working in the app now (``_run_in_the_app``), by id: to cut off.
_working: dict[int, asyncio.Task[None]] = {}


class ActionNotFoundError(LookupError):
    """No action by that name runs anywhere a run can be made for."""


class MomentNotFoundError(LookupError):
    """No moment by that id is this owner's."""


# The most of a meeting's name a run's place keeps: what a run keeps of a
# place, less the words and the day around the name.
MOST_NAME = MOST_TITLE - len("Meeting ·  · 0000-00-00")


def _place(meeting_id: int, called: str | None, held: datetime) -> str:
    """Where a run about one of a meeting's moments was asked: by its
    calendar's name for it and its day (UTC; one held every week is called
    the same each time, and a list of runs folds by place), else as its
    page is headed. A long name is cut so its day always fits."""
    if not called:
        return f"Meeting {meeting_id}"
    return f"Meeting · {called[:MOST_NAME]} · {held:%Y-%m-%d}"


async def ask(
    db: AsyncSession,
    moment_id: int,
    action_name: str,
    *,
    owner_user_id: int | None,
    meeting_id: int | None = None,
    together: list[MeetingMoment] | None = None,
) -> RunnerRun:
    """Ask ``action_name`` of the moment (in ``meeting_id``, when given), and
    of those said ``together`` with it after it (its burst): a run about
    the moment, its meeting's owner's, with the prompt the action frames
    from them all. One that runs in the app starts at once. Asked again
    while the last is still going, it is that run; once that is back, the
    new run replaces it (one answer per action, over every moment of the
    card)."""
    action = action_named(action_name)
    if action is None or action.where == "browser":
        raise ActionNotFoundError(action_name)
    found = await queries.moment(db, moment_id, owner_user_id, meeting_id)
    if found is None:
        raise MomentNotFoundError(moment_id)
    moment, owner, called, held = found
    card = [moment, *(together or [])]
    ids = subjects(m.id or 0 for m in card)
    going = await runs.going(db, MOMENT, ids, action.name)
    if going is not None:
        return going
    run = await runs.ask(
        db,
        owner_user_id=owner,
        kind=MOMENT,
        subject_id=ids[0],
        action=action.name,
        # What a list of runs calls it: its card's topic, else the question.
        title=moment.topic or moment.text,
        source=_place(moment.meeting_id, called, held),
        prompt=action.frame(await excerpt(db, card)),
        replacing=ids,
    )
    if action.where == IN_THE_APP:
        _working[run.id or 0] = background(_run_in_the_app(run.id or 0, action))
    return run


async def drop(db: AsyncSession, moment_ids: list[int], result: str = STOPPED) -> None:
    """Every run still going on these moments stopped: each failed as
    ``result`` (``STOPPED``), never finished, and those working in the app
    cut off."""
    for run_id in await runs.stop(db, MOMENT, subjects(moment_ids), result):
        if (task := _working.pop(run_id, None)) is not None:
            task.cancel()


async def forget(db: AsyncSession, meeting_id: int) -> None:
    """The meeting's runs gone, as it is going. The caller commits."""
    await runs.forget(db, MOMENT, queries.asked_in(meeting_id))


async def hand_over(
    db: AsyncSession, meeting_id: int, owner_user_id: int | None
) -> None:
    """The meeting's runs made ``owner_user_id``'s, as it is: theirs to
    claim. The caller commits."""
    await runs.hand_over(db, MOMENT, queries.asked_in(meeting_id), owner_user_id)


async def _run_in_the_app(run_id: int, action: Action) -> None:
    """Claim the run as the app, run the action, and finish it with what it
    returned, or why it failed."""
    async with get_async_session() as db:
        if not await runs.take(db, run_id, IN_THE_APP):
            return
        run = await db.get_one(RunnerRun, run_id)
        moment = await db.get_one(MeetingMoment, moment_of(run))
        prompt, kind, asked, owner = (
            run.prompt,
            moment.kind,
            moment.id or 0,
            run.owner_user_id,
        )
    try:
        if action.run is None:
            raise ActionNotFoundError(f"{action.name} has nothing to run in the app")
        with aloud(kind), asking(asked):
            result, ok = await action.run(prompt, owner), True
    except Exception as exc:
        logger.exception("Action failed", action=action.name, run_id=run_id)
        result, ok = str(exc) or type(exc).__name__, False
    _working.pop(run_id, None)
    async with get_async_session() as db:
        try:
            await runs.finish(db, run_id, owner, result, ok=ok, runner=IN_THE_APP)
        except RunNotFoundError:  # stopped (``drop``) as it came back
            logger.info("Action stopped before its answer landed", run_id=run_id)
