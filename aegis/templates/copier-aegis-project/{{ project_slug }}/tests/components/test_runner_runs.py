"""Runs: asked about a subject of its asker's, claimed by one runner only,
finished by what claimed it, and failed when that goes quiet."""

import asyncio
from datetime import timedelta

import pytest
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.runner import hooks, runs
from app.components.runner.models import (
    CLAIMED,
    DONE,
    FAILED,
    MOST_ACTIVITY,
    MOST_AGENT,
    MOST_LINE,
    MOST_STEPS,
    MOST_TITLE,
    RunnerRun,
    RunnerSpend,
    RunnerStep,
)
from app.components.runner.protocol import CALLED, PUSH, RETURNED, SAID, Line
from app.core.time import utcnow
from tests._runner import ISSUE, a_run, answered, asked, claimed, late, someone_else


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


async def _spent(db: AsyncSession) -> list[tuple[str, float]]:
    """What was written down as spent, by action, in the order it was."""
    rows = await db.exec(select(RunnerSpend).order_by(col(RunnerSpend.id)))
    return [(row.action, row.cost) for row in rows.all()]


async def test_what_a_run_cost_is_written_down_apart_from_it(
    async_db_session: AsyncSession,
) -> None:
    """So a run replaced by a later ask, or forgotten with its subject, does
    not take what it cost with it."""
    db = async_db_session
    run = await answered(db, await asked(db), cost=0.4)

    await runs.forget(db, ISSUE, [run.subject_id])
    await db.commit()

    assert await _spent(db) == [("agent", 0.4)]


@pytest.mark.parametrize(
    ("how", "status", "kept"),
    [("stopped", FAILED, 0.1), ("overdue", FAILED, 0.1), ("another", CLAIMED, None)],
)
async def test_what_a_stopped_or_overdue_run_cost_is_kept_and_it_stays_failed(
    async_db_session: AsyncSession, how: str, status: str, kept: float | None
) -> None:
    """Its agent was working while it was stopped, or past when it was due:
    what its runner says it cost is spent all the same, and the run is not
    answered after all. Only the runner that held it says."""
    db = async_db_session
    run = await claimed(db, await asked(db))
    if how == "stopped":
        await runs.stop(db, ISSUE, [run.subject_id])
    elif how == "overdue":
        await late(db, run, 24 * 60)
        await runs.fail_abandoned(db)
    runner = "desk" if how == "another" else "laptop"

    with pytest.raises(runs.RunNotFoundError):
        await runs.finish(
            db, run.id or 0, None, "Late.", ok=True, runner=runner, cost=0.1
        )

    await db.refresh(run)
    assert (run.status, run.cost) == (status, kept)
    assert await _spent(db) == ([("agent", 0.1)] if kept else [])


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
    await late(async_db_session, gone, 31)
    await late(async_db_session, long, 31)

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


async def _steps(db: AsyncSession, run: RunnerRun) -> list[str]:
    """The steps a run keeps, in the order its agent took them."""
    return [step.step for step in await runs.steps(db, run.id or 0)]


@pytest.mark.parametrize(
    ("said", "kept"),
    [
        ("Edit app/main.py", ["Read app/main.py", "Edit app/main.py"]),
        (hooks.NOTHING, ["Read app/main.py"]),
    ],
)
async def test_a_run_keeps_each_step_its_agent_took(
    async_db_session: AsyncSession, said: str, kept: list[str]
) -> None:
    """A step goes after the ones before it, so a run that is over can say
    what its agent did; ending its turn is no step."""
    db = async_db_session
    run = await claimed(db, await asked(db))
    db.add(RunnerStep(run_id=run.id or 0, step="Read app/main.py"))
    await db.commit()

    await runs.note(db, None, run.session_id or "", said)

    assert await _steps(db, run) == kept


async def test_a_run_keeps_so_many_steps_and_still_says_the_latest(
    async_db_session: AsyncSession,
) -> None:
    """An agent in a loop cannot fill the table: past ``MOST_STEPS`` a step
    is what the run is doing, and not kept."""
    db = async_db_session
    run = await claimed(db, await asked(db))
    db.add_all(
        RunnerStep(run_id=run.id or 0, step=f"Read {n}") for n in range(MOST_STEPS)
    )
    await db.commit()

    await runs.note(db, None, run.session_id or "", "Edit app/main.py")
    await runs.hear(
        db, run.id or 0, None, "laptop", [Line(kind=SAID, text="Still here.")]
    )

    kept = await _steps(db, run)
    # Its session is kept apart: its hooks' steps leave its lines room.
    assert (len(kept), kept[-2:]) == (
        MOST_STEPS + 1,
        [f"Read {MOST_STEPS - 1}", "Still here."],
    )
    assert await _doing(db, run) == ["Edit app/main.py"]


async def test_a_runs_steps_go_with_it(async_db_session: AsyncSession) -> None:
    """Forgetting a run (or asking one in its place) forgets what its agent
    did; another run's steps stay."""
    db = async_db_session
    gone, kept = await asked(db, "acme/app#1"), await asked(db, "acme/app#2")
    db.add_all(RunnerStep(run_id=run.id or 0, step="Read") for run in (gone, kept))
    await db.commit()

    await runs.forget(db, ISSUE, ["acme/app#1"])
    await db.commit()

    left = (await db.exec(select(RunnerStep.run_id))).all()
    assert left == [kept.id]


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
    failed and what was spent since a time, and nothing from before it.
    What was spent is what was written down, the runs it was spent on kept
    or not: an action whose runs are all gone still says it."""
    now = utcnow()
    since = now - timedelta(days=7)
    async_db_session.add_all(
        [
            a_run(status=DONE, finished_at=now),
            a_run(status=FAILED, finished_at=since - timedelta(days=1)),
            a_run(status=FAILED, finished_at=now),
            a_run(status=CLAIMED),
            a_run(),
            a_run(action="ai"),
            RunnerSpend(action="agent", cost=0.25, at=now),
            RunnerSpend(action="agent", cost=0.5, at=now),  # a replaced run's
            RunnerSpend(action="agent", cost=1.0, at=since - timedelta(days=1)),
            RunnerSpend(action="gone", cost=0.1, at=now),
        ]
    )
    await async_db_session.flush()

    assert await runs.tally(async_db_session, since) == [
        runs.Tally("agent", waiting=1, running=1, failed=1, cost=0.75),
        runs.Tally("ai", waiting=1, running=0, failed=0, cost=0.0),
        runs.Tally("gone", waiting=0, running=0, failed=0, cost=0.1),
    ]


async def test_a_claimed_run_keeps_only_so_much_of_its_agents_name(
    async_db_session: AsyncSession,
) -> None:
    """Whatever claims it: a runner cuts the name before it says it, and
    the app cuts what it is told."""
    run = await asked(async_db_session)

    taken = await claimed(async_db_session, run, agent="c" * 100)

    assert taken.agent == "c" * MOST_AGENT


async def test_a_run_back_on_a_branch_says_what_is_left_to_push(
    async_db_session: AsyncSession,
) -> None:
    """Its runner counts its branch's commits the remote does not have."""
    db = async_db_session
    run = await asked(db, branch="issue-12-export")

    back = await answered(db, run, unpushed=2)

    assert back.unpushed == 2


async def test_pushing_a_run_asks_its_runner_to_push_its_branch(
    async_db_session: AsyncSession,
) -> None:
    """A run of its own, the runner's and never its agent's, on the same
    branch, about the same subject, closing it where it is an issue on
    GitHub."""
    db = async_db_session
    run = await answered(db, await asked(db, branch="issue-12-export"), unpushed=1)

    push = await runs.push(db, run)

    assert (push.action, push.branch, push.subject_id) == (
        PUSH,
        "issue-12-export",
        "acme/app#12",
    )
    assert push.prompt == "Closes acme/app#12" and push.id != run.id


@pytest.mark.parametrize(
    ("branch", "same"), [("issue-12-export", True), ("issue-12-retry", False)]
)
async def test_a_push_asked_while_one_goes_on_its_branch_is_that_one(
    async_db_session: AsyncSession, branch: str, same: bool
) -> None:
    """Not while one goes on another branch of the same subject."""
    db = async_db_session
    run = await answered(db, await asked(db, branch="issue-12-export"), unpushed=1)
    going = a_run(action=PUSH, branch=branch)
    db.add(going)
    await db.commit()

    push = await runs.push(db, run)

    assert (push.id == going.id) is same


async def test_a_run_back_keeps_whether_its_agent_answered(
    async_db_session: AsyncSession,
) -> None:
    db = async_db_session

    back = await answered(db, await asked(db), "Nothing in the notes.", unanswered=True)

    assert back.unanswered is True


async def _lines(db: AsyncSession, run: RunnerRun) -> list[tuple[str | None, str]]:
    return [(step.kind, step.step) for step in await runs.steps(db, run.id or 0)]


async def test_a_run_keeps_its_agents_session_as_its_runner_hears_it(
    async_db_session: AsyncSession,
) -> None:
    """In order after its steps, cut to a length, and a line that looks
    like a key masked before it is kept."""
    db = async_db_session
    run = await claimed(db, await asked(db))
    long = "x" * (MOST_LINE + 50)
    said = [
        Line(kind=CALLED, text="Bash env"),
        Line(
            kind=RETURNED,
            text="HOME=/root\nOPENAI_API_KEY=sk-live-abcdefghij1234\nghp_abcdefghijklmnopqrst12",
        ),
        Line(kind=SAID, text=long),
    ]

    await runs.hear(db, run.id or 0, None, "laptop", said)

    assert await _lines(db, run) == [
        (CALLED, "Bash env"),
        (RETURNED, "HOME=/root\nOPENAI_API_KEY=[redacted]\n[redacted]"),
        (SAID, long[:MOST_LINE]),
    ]


@pytest.mark.parametrize("by", ["another", "stopped"])
async def test_a_session_is_kept_only_from_the_runner_holding_its_run(
    async_db_session: AsyncSession, by: str
) -> None:
    db = async_db_session
    run = await claimed(db, await asked(db))
    if by == "stopped":
        await runs.stop(db, ISSUE, ["acme/app#12"])

    await runs.hear(
        db,
        run.id or 0,
        None,
        "laptop" if by == "stopped" else "desktop",
        [Line(kind=SAID, text="Hi.")],
    )

    assert await _lines(db, run) == []


async def test_what_an_agent_says_is_kept_with_its_keys_hidden(
    async_db_session: AsyncSession,
) -> None:
    """What it is doing and what it came back with, as its session's lines."""
    db = async_db_session
    run = await claimed(db, await asked(db))

    await runs.note(db, None, run.session_id or "", "Bash export GITHUB_TOKEN=ghp_x")
    back = await runs.finish(
        db, run.id or 0, None, "Used api_key=abc123.", ok=True, runner="laptop"
    )

    assert (back.activity, back.result) == (
        "Bash export GITHUB_TOKEN=[redacted]",
        "Used api_key=[redacted]",
    )
