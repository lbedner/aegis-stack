"""Runs: asked about a subject of its asker's, claimed by one runner only,
finished by what claimed it, and failed when that goes quiet."""

import asyncio

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.runner import runs
from tests._runner import ISSUE, asked, someone_else


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


async def test_a_run_whose_runner_went_quiet_fails(
    async_db_session: AsyncSession,
) -> None:
    await asked(async_db_session, "acme/app#1")
    await asked(async_db_session, "acme/app#2")
    gone = await runs.claim(async_db_session, None, ["agent"], runner="laptop")
    live = await runs.claim(async_db_session, None, ["agent"], runner="desk")
    assert gone is not None and live is not None
    gone.claimed_at -= runs.ABANDONED_AFTER  # type: ignore[operator]
    async_db_session.add(gone)
    await async_db_session.commit()

    assert await runs.fail_abandoned(async_db_session) == 1

    about = await runs.about(async_db_session, ISSUE, ["acme/app#1", "acme/app#2"])
    assert [(r.runner, r.status) for r in about] == [
        ("laptop", "failed"),
        ("desk", "claimed"),
    ]


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
