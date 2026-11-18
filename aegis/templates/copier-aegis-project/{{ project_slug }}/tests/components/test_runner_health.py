"""The runner's health check: how many runs wait and how many a runner
has, across every owner, and whether a runner is listening. A run waiting
on no runner that takes its owner's is the warning: nothing answers it."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.runner import health, runs
from app.components.runner.health import RunnerFact, check_runner_health
from app.core.constants import ComponentName
from app.services.system.models import ComponentStatusType
from tests._runner import a_runner_looked_in, asked, someone_else
from tests._session import opens


@pytest.fixture
def db(async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    monkeypatch.setattr(health, "get_async_session", opens(async_db_session))
    return async_db_session


async def test_a_stack_that_asked_nothing_is_healthy_with_no_runner(
    db: AsyncSession,
) -> None:
    status = await check_runner_health()

    assert status.name == ComponentName.RUNNER
    assert status.status is ComponentStatusType.HEALTHY
    assert status.metadata == {
        RunnerFact.WAITING: 0,
        RunnerFact.RUNNING: 0,
        RunnerFact.LISTENING: False,
    }


async def test_runs_waiting_on_no_runner_are_a_warning(db: AsyncSession) -> None:
    await asked(db)

    status = await check_runner_health()

    assert status.status is ComponentStatusType.WARNING
    assert status.message == "1 waiting, 0 running, 1 with no runner listening"


async def test_it_counts_what_waits_and_what_a_runner_has(db: AsyncSession) -> None:
    first = await asked(db)
    await asked(db, "acme/app#13")
    done = await asked(db, "acme/app#14")
    await a_runner_looked_in(db)
    for run in (first, done):
        assert await runs.take(db, run.id or 0, "laptop")
    await runs.finish(db, done.id or 0, None, "Fixed.", ok=True, runner="laptop")

    status = await check_runner_health()

    assert status.status is ComponentStatusType.HEALTHY
    assert status.message == "1 waiting, 1 running"
    assert status.metadata == {
        RunnerFact.WAITING: 1,
        RunnerFact.RUNNING: 1,
        RunnerFact.LISTENING: True,
    }


@pytest.mark.parametrize(
    ("whose", "status"),
    [
        ("theirs", ComponentStatusType.WARNING),
        ("mine", ComponentStatusType.HEALTHY),
        ("everyone's", ComponentStatusType.HEALTHY),
    ],
)
async def test_only_a_runner_that_takes_the_owners_runs_answers_them(
    db: AsyncSession, whose: str, status: ComponentStatusType
) -> None:
    """A runner claims its token's owner's runs, or every owner's: one
    listening for someone else leaves this owner's run waiting for good,
    and the check says so though a runner is listening."""
    mine, theirs = await someone_else(db), await someone_else(db)
    await asked(db, owner_user_id=mine)
    await a_runner_looked_in(db, {"theirs": theirs, "mine": mine}.get(whose))

    found = await check_runner_health()

    assert found.status is status
    assert found.metadata[RunnerFact.LISTENING] is True
