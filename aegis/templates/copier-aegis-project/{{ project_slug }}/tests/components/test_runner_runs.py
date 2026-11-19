"""Runs: asked about a subject of its asker's, claimed by one runner only,
finished by what claimed it, and failed when that goes quiet."""

import asyncio
from datetime import timedelta

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.runner import hooks, runs
from app.components.runner.models import (
    CLAIMED,
    DONE,
    FAILED,
    MOST_ACTIVITY,
    MOST_AGENT,
    MOST_TITLE,
    RunnerRun,
)
from app.core.time import utcnow
from tests._runner import ISSUE, a_run, answered, asked, claimed, someone_else


async def test_a_runner_claims_a_run_once_and_finishes_it(
    async_db_session: AsyncSession,
) -> None:
    run = await asked(async_db_session)

    claimed = await runs.claim(async_db_session, None, ["agent"], runner="laptop")
    assert claimed is not None and claimed.id == run.id
    assert (claimed.status, claimed.runner) == ("claimed", "laptop")
    assert await runs.claim(async_db_session, None, ["agent"], runner="desk") is None

    done = await runs.finish(
        async_db_session, claimed.id or 0, None, "Fixed.", ok=True, runner="laptop"
    )

    assert (done.status, done.result) == ("done", "Fixed.")
    assert done.finished_at is not None


async def test_only_what_claimed_a_run_finishes_it(
    async_db_session: AsyncSession,
) -> None:
    """Another of the owner's runners cannot post over a claimed run: the
    answer would be lost."""
    run = await asked(async_db_session)
    await runs.claim(async_db_session, None, ["agent"], runner="laptop")

    with pytest.raises(runs.RunNotFoundError):
        await runs.finish(
            async_db_session, run.id or 0, None, "Not mine", ok=True, runner="desk"
        )

    failed = await runs.finish(
        async_db_session, run.id or 0, None, "No repo", ok=False, runner="laptop"
    )
    assert (failed.status, failed.result) == ("failed", "No repo")


async def test_a_run_stopped_after_it_was_claimed_is_not_answered_after_all(
    async_db_session: AsyncSession,
) -> None:
    run = await asked(async_db_session)
    await runs.claim(async_db_session, None, ["agent"], runner="laptop")
    await runs.stop(async_db_session, ISSUE, [run.subject_id])

    with pytest.raises(runs.RunNotFoundError):
        await runs.finish(
            async_db_session, run.id or 0, None, "Late.", ok=True, runner="laptop"
        )

    over = await runs.answered(async_db_session, ISSUE, [run.subject_id], "agent")
    assert over == {run.subject_id: ("failed", runs.STOPPED)}


async def test_a_runner_claims_only_its_owners_runs_and_its_actions(
    async_db_session: AsyncSession,
) -> None:
    """A runner holds one owner's token and names the actions it runs; one
    for every owner (no owner) claims anyone's."""
    theirs = await someone_else(async_db_session)
    await asked(async_db_session, owner_user_id=theirs)
    other = await someone_else(async_db_session)

    assert await runs.claim(async_db_session, other, ["agent"], runner="a") is None
    assert await runs.claim(async_db_session, theirs, ["other"], runner="a") is None
    assert await runs.claim(async_db_session, None, ["agent"], runner="a") is not None


async def _late(db: AsyncSession, run: RunnerRun, minutes: int) -> None:
    """``run`` as if it had been claimed ``minutes`` earlier than it was."""
    by = timedelta(minutes=minutes)
    run.claimed_at -= by  # type: ignore[operator]
    run.overdue_at -= by  # type: ignore[operator]
    db.add(run)
    await db.commit()


async def test_a_run_whose_runner_went_quiet_fails(
    async_db_session: AsyncSession,
) -> None:
    """A run is waited for twice what its runner gives a command (half an
    hour, where the runner did not say): past that it is never coming
    back, and fails so nothing waits on it."""
    await asked(async_db_session, "acme/app#1")
    await asked(async_db_session, "acme/app#2")
    await asked(async_db_session, "acme/app#3")
    gone = await runs.claim(async_db_session, None, ["agent"], runner="laptop")
    live = await runs.claim(async_db_session, None, ["agent"], runner="desk")
    long = await runs.claim(
        async_db_session, None, ["agent"], runner="tower", timeout=3600
    )
    assert gone is not None and live is not None and long is not None
    await _late(async_db_session, gone, 31)
    await _late(async_db_session, long, 31)

    assert await runs.fail_abandoned(async_db_session) == 1

    about = await runs.about(
        async_db_session, ISSUE, ["acme/app#1", "acme/app#2", "acme/app#3"]
    )
    assert [(r.runner, r.status) for r in about] == [
        ("laptop", "failed"),
        ("desk", "claimed"),
        ("tower", "claimed"),
    ]


async def test_a_run_claimed_before_runs_said_when_they_are_due_still_fails(
    async_db_session: AsyncSession,
) -> None:
    await asked(async_db_session)
    old = await runs.claim(async_db_session, None, ["agent"], runner="laptop")
    assert old is not None
    old.overdue_at = None
    old.claimed_at -= runs.ABANDONED_AFTER  # type: ignore[operator]
    async_db_session.add(old)
    await async_db_session.commit()

    assert await runs.fail_abandoned(async_db_session) == 1


async def test_a_subjects_runs_are_read_stopped_and_forgotten_by_subject(
    async_db_session: AsyncSession,
) -> None:
    mine = await asked(async_db_session, "acme/app#1")
    await asked(async_db_session, "acme/app#2")
    await asked(async_db_session, "1", kind="moment")  # another asker's

    going = await runs.going(async_db_session, ISSUE, ["acme/app#1"], "agent")
    assert going is not None and going.id == mine.id

    assert await runs.stop(async_db_session, ISSUE, ["acme/app#1"]) == [mine.id]
    over = await runs.answered(async_db_session, ISSUE, ["acme/app#1"], "agent")
    assert over == {"acme/app#1": ("failed", runs.STOPPED)}

    await runs.forget(async_db_session, ISSUE, ["acme/app#1", "acme/app#2"])
    await async_db_session.commit()
    assert await runs.about(async_db_session, ISSUE, ["acme/app#1", "acme/app#2"]) == []
    assert len(await runs.about(async_db_session, "moment", ["1"])) == 1


async def test_a_run_asked_in_place_of_others_replaces_them(
    async_db_session: AsyncSession,
) -> None:
    """An asker that keeps one answer per action names the subjects whose
    runs of it the new one replaces; their runs of another action stay."""
    await asked(async_db_session, "acme/app#1")
    kept = await asked(async_db_session, "acme/app#2", action="review")

    latest = await asked(
        async_db_session, "acme/app#2", replacing=["acme/app#1", "acme/app#2"]
    )

    about = await runs.about(async_db_session, ISSUE, ["acme/app#1", "acme/app#2"])
    assert [r.id for r in about] == [kept.id, latest.id]


async def test_runs_handed_over_are_the_new_owners_to_claim(
    async_db_session: AsyncSession,
) -> None:
    theirs = await someone_else(async_db_session)
    mine = await someone_else(async_db_session)
    run = await asked(async_db_session, owner_user_id=theirs)

    await runs.hand_over(async_db_session, ISSUE, [run.subject_id], mine)
    await async_db_session.commit()

    claimed = await runs.claim(async_db_session, mine, ["agent"], runner="laptop")
    assert claimed is not None and claimed.id == run.id


async def test_whoever_watches_hears_a_run_asked_taken_and_finished_at_once(
    async_db_session: AsyncSession,
) -> None:
    heard: list[str] = []

    with runs.watching(lambda: heard.append("changed")):
        run = await asked(async_db_session)
        await runs.claim(async_db_session, None, ["agent"], runner="laptop")
        await runs.finish(
            async_db_session, run.id or 0, None, "Done.", ok=True, runner="laptop"
        )
    await asked(async_db_session, "acme/app#13")

    assert heard == ["changed"] * 3  # asked, taken, finished; then nobody


async def test_the_sweep_for_abandoned_runs_outlives_a_failed_check(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A database out of reach for one check (a refused connection is no
    SQLAlchemy error) is said and tried again: the sweep is not over for
    the life of the process."""
    from app.components.backend.startup import runner_recovery
    from tests._session import opens

    checks: list[int] = []

    async def check(db: AsyncSession) -> int:
        checks.append(1)
        if len(checks) == 1:
            raise ConnectionRefusedError("down")
        if len(checks) == 3:
            raise asyncio.CancelledError
        return 0

    monkeypatch.setattr(runner_recovery, "SWEEP_SECONDS", 0)
    monkeypatch.setattr(runner_recovery, "get_async_session", opens(async_db_session))
    monkeypatch.setattr(runner_recovery.runs, "fail_abandoned", check)

    with pytest.raises(asyncio.CancelledError):
        await runner_recovery.sweep_forever()

    assert len(checks) == 3


async def test_work_is_asked_on_a_branch_in_a_session_the_app_names(
    async_db_session: AsyncSession,
) -> None:
    """The session is chosen when the run is asked, so whoever asked can be
    told how to pick it up before the agent has answered."""
    session = runs.new_session()

    run = await asked(async_db_session, branch="issue-12-export", session_id=session)

    assert (run.branch, run.session_id) == ("issue-12-export", session)
    assert not await runs.resumes(async_db_session, run)


async def test_a_claimed_run_on_a_branch_says_where_its_work_will_be(
    async_db_session: AsyncSession,
) -> None:
    """From the moment a runner takes it, not when it is back: a run that
    is stopped or never returns is the one someone picks up by hand."""
    work = await asked(async_db_session, branch="issue-12", session_id="0f0f")
    await asked(async_db_session, "acme/app#13")

    taken = await claimed(async_db_session, work, worktrees="/code/app-worktrees")
    question = await runs.claim(
        async_db_session,
        None,
        ["agent"],
        runner="laptop",
        worktrees="/code/app-worktrees",
    )
    await runs.stop(async_db_session, ISSUE, [work.subject_id])

    assert question is not None and question.worktree is None
    await async_db_session.refresh(taken)
    assert (taken.status, taken.worktree) == ("failed", "/code/app-worktrees/issue-12")


async def test_a_finished_run_says_where_its_work_is_as_its_runner_found_it(
    async_db_session: AsyncSession,
) -> None:
    run = await asked(async_db_session, branch="issue-12", session_id="0f0f")

    done = await answered(async_db_session, run, cost=0.37, worktree="/w/issue-12")

    assert (done.cost, done.worktree) == (0.37, "/w/issue-12")


# Four runs finished one after another: a loop by construction.
@pytest.mark.queryspy(allow_n_plus_one=True)
async def test_a_follow_up_costs_what_it_added_to_its_session(
    async_db_session: AsyncSession,
) -> None:
    """An agent says what its whole session has cost so far. Each run
    keeps its own share, so a session's cost is the sum of its runs', and
    a session that began again costs nothing twice."""
    first = await asked(async_db_session, session_id="0f0f")
    second = await asked(async_db_session, session_id="0f0f")
    third = await asked(async_db_session, session_id="0f0f")
    other = await asked(async_db_session, "acme/app#13", session_id="1a1a")

    costs = [
        (await answered(async_db_session, run, cost=total)).cost
        for run, total in ((first, 0.4), (second, 0.5), (third, 0.3), (other, 0.2))
    ]

    assert costs == pytest.approx([0.4, 0.1, 0.0, 0.2])


# Two runs finished one after another: a loop by construction.
@pytest.mark.queryspy(allow_n_plus_one=True)
async def test_runs_of_a_session_answered_out_of_order_still_sum_to_its_cost(
    async_db_session: AsyncSession,
) -> None:
    """Two runners may have a session's runs at once: whichever answers
    second keeps only what the other has not."""
    first = await asked(async_db_session, session_id="0f0f")
    second = await asked(async_db_session, session_id="0f0f")
    await claimed(async_db_session, first)

    late = await answered(async_db_session, second, cost=0.2)
    early = await runs.finish(
        async_db_session,
        first.id or 0,
        None,
        "Done.",
        ok=True,
        runner="laptop",
        cost=0.3,
    )

    assert [early.cost, late.cost] == pytest.approx([0.1, 0.2])


async def test_a_later_run_of_a_session_a_runner_took_tries_to_resume_it(
    async_db_session: AsyncSession,
) -> None:
    """A session cannot be started twice. Once a runner took a run of it
    the agent may have begun it, whether or not that run came back with an
    answer (it may have timed out, or been stopped): the next run resumes,
    and its runner starts the session instead if the agent never had it."""
    first = await asked(async_db_session, branch="issue-12", session_id="0f0f")
    second = await asked(async_db_session, branch="issue-12", session_id="0f0f")

    await claimed(async_db_session, first)

    assert await runs.resumes(async_db_session, second)


async def test_a_session_no_runner_took_is_started(
    async_db_session: AsyncSession,
) -> None:
    await asked(async_db_session, branch="issue-12", session_id="0f0f")
    second = await asked(async_db_session, branch="issue-12", session_id="0f0f")

    assert not await runs.resumes(async_db_session, second)


async def test_one_sessions_run_resumes_no_other(
    async_db_session: AsyncSession,
) -> None:
    first = await asked(async_db_session, session_id="0f0f")
    other = await asked(async_db_session, "acme/app#13", session_id="1a1a")

    await claimed(async_db_session, first)

    assert not await runs.resumes(async_db_session, other)


async def test_a_run_claimed_with_no_session_is_given_one(
    async_db_session: AsyncSession,
) -> None:
    """Every claimed run has a session the app knows: what its agent's
    hooks say is found by it."""
    run = await asked(async_db_session)

    taken = await claimed(async_db_session, run)

    assert taken.session_id and len(taken.session_id) == 36


async def _doing(db: AsyncSession, *some: RunnerRun) -> list[str | None]:
    """What each run says it is doing, as the database has it."""
    said = dict((await db.exec(select(RunnerRun.id, RunnerRun.activity))).all())
    return [said[run.id] for run in some]


async def test_what_an_agent_is_doing_goes_on_the_run_going_in_its_session(
    async_db_session: AsyncSession,
) -> None:
    """A hook knows its session, not its run: the latest run a runner took
    in it is the one going (or, picked up from a terminal, the one it
    continues). A follow-up still waiting to be claimed is not it yet."""
    first = await asked(async_db_session, "acme/app#1", session_id="0f0f")
    await answered(async_db_session, first)
    going = await asked(async_db_session, "acme/app#2", session_id="0f0f")
    await claimed(async_db_session, going)
    waiting = await asked(async_db_session, "acme/app#3", session_id="0f0f")
    other = await asked(async_db_session, "acme/app#4", session_id="1a1a")

    await runs.note(async_db_session, None, "0f0f", "Edit app/core/tokens.py")

    assert await _doing(async_db_session, first, going, waiting, other) == [
        None,
        "Edit app/core/tokens.py",
        None,
        None,
    ]
    await async_db_session.refresh(going)
    assert going.activity_at is not None


async def test_an_agent_that_ended_its_turn_is_doing_nothing(
    async_db_session: AsyncSession,
) -> None:
    """What a run is doing is for now: it does not outlast the turn."""
    run = await claimed(async_db_session, await asked(async_db_session))
    run.activity = "Bash make test"
    await async_db_session.commit()

    await runs.note(async_db_session, None, run.session_id or "", hooks.NOTHING)

    assert await _doing(async_db_session, run) == [None]


async def test_a_long_step_is_cut_to_what_a_run_keeps(
    async_db_session: AsyncSession,
) -> None:
    run = await claimed(async_db_session, await asked(async_db_session))

    await runs.note(async_db_session, None, run.session_id or "", "x" * 1000)

    (kept,) = await _doing(async_db_session, run)
    assert len(kept or "") == MOST_ACTIVITY


async def test_a_step_in_a_session_nobody_asked_a_run_in_changes_nothing(
    async_db_session: AsyncSession,
) -> None:
    run = await claimed(async_db_session, await asked(async_db_session))

    await runs.note(async_db_session, None, "never-asked", "Bash make test")

    assert await _doing(async_db_session, run) == [None]


async def test_only_a_sessions_owner_says_what_it_is_doing(
    async_db_session: AsyncSession,
) -> None:
    theirs = await someone_else(async_db_session)
    mine = await someone_else(async_db_session)
    run = await asked(async_db_session, owner_user_id=theirs, session_id="0f0f")
    assert await runs.claim(async_db_session, theirs, ["agent"], runner="laptop")

    await runs.note(async_db_session, mine, "0f0f", "Bash rm -rf /")

    assert await _doing(async_db_session, run) == [None]


@pytest.mark.parametrize(("ok", "kept"), [(True, "a"), (False, "b")])
async def test_a_run_keeps_only_so_much_of_what_came_back(
    async_db_session: AsyncSession, ok: bool, kept: str
) -> None:
    """Whatever posts a result, the app keeps a page's worth of it: the
    start of an answer, the end of a failure, where the error is."""
    from app.components.runner.protocol import KEEP

    run = await asked(async_db_session)

    done = await answered(async_db_session, run, "a" * KEEP + "b" * KEEP, ok=ok)

    assert done.result == kept * KEEP


async def test_a_run_says_in_words_what_was_asked_and_where(
    async_db_session: AsyncSession,
) -> None:
    """Its subject is an id; whatever asks it says what a reader calls it
    (cut to what a run keeps) and where it was asked."""
    run = await asked(
        async_db_session, title="Can the export ship? " * 40, source="Weekly sync"
    )

    assert run.title == ("Can the export ship? " * 40)[:MOST_TITLE]
    assert run.source == "Weekly sync"
    assert (await asked(async_db_session, "acme/app#13")).title is None


async def test_the_newest_runs_can_be_kept_to_one_action(
    async_db_session: AsyncSession,
) -> None:
    await asked(async_db_session)
    theirs = await asked(async_db_session, "acme/app#13", action="ai")

    kept = await runs.latest(async_db_session, 10, "ai")

    assert [run.id for run, _ in kept] == [theirs.id]


async def test_the_newest_runs_say_whether_anything_came_back(
    async_db_session: AsyncSession,
) -> None:
    """What came back is not read for a list; whether anything did is."""
    async_db_session.add_all(
        [a_run(status=DONE, result="Fixed."), a_run(status=DONE, result="")]
    )
    await async_db_session.flush()

    assert [back for _, back in await runs.latest(async_db_session, 10)] == [
        False,
        True,
    ]


async def test_a_tally_says_how_each_actions_runs_stand_and_what_they_cost_lately(
    async_db_session: AsyncSession,
) -> None:
    """Per action: what waits and what a runner has, whenever asked; what
    failed and what was spent since a time, and nothing from before it."""
    now = utcnow()
    since = now - timedelta(days=7)
    async_db_session.add_all(
        [
            a_run(status=DONE, cost=0.25, finished_at=now),
            a_run(status=FAILED, cost=1.0, finished_at=since - timedelta(days=1)),
            a_run(status=FAILED, finished_at=now),
            a_run(status=CLAIMED),
            a_run(),
            a_run(action="ai"),
        ]
    )
    await async_db_session.flush()

    assert await runs.tally(async_db_session, since) == [
        runs.Tally("agent", waiting=1, running=1, failed=1, cost=0.25),
        runs.Tally("ai", waiting=1, running=0, failed=0, cost=0.0),
    ]


async def test_a_claimed_run_keeps_only_so_much_of_its_agents_name(
    async_db_session: AsyncSession,
) -> None:
    """Whatever claims it: a runner cuts the name before it says it, and
    the app cuts what it is told."""
    run = await asked(async_db_session)

    taken = await claimed(async_db_session, run, agent="c" * 100)

    assert taken.agent == "c" * MOST_AGENT
