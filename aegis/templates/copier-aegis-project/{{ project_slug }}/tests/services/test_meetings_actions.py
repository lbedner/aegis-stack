"""Actions: what can be done with a moment. Each is registered by name with
the kinds of moment it takes and where it runs: in the browser (copied),
in the app, or on a runner on another machine. Asking one makes a run,
claimed once by what runs it and finished with what it came back with."""

from collections.abc import Awaitable
from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.services.meetings.domains.actions import registry, runs
from app.services.meetings.domains.actions.registry import Action, register_action
from app.services.meetings.domains.actions.runs import (
    ActionNotFoundError,
    ask,
    claim,
    finish,
)
from app.services.meetings.domains.moments.service import moments_of
from app.services.meetings.models import MeetingMoment
from tests._meetings import asked_a_question


@pytest.fixture
def held(monkeypatch: pytest.MonkeyPatch) -> list[Awaitable[Any]]:
    """In-app runs, kept to await instead of started in the background."""
    started: list[Awaitable[Any]] = []
    monkeypatch.setattr(runs, "background", started.append)
    return started


def test_a_question_offers_the_built_in_actions() -> None:
    offered = {a.name: a for a in registry.actions_for("question")}

    assert offered["copy"].where == "browser"
    assert offered["agent"].where == "runner"
    assert offered["agent"].label == "Ask agent"


async def test_the_prompt_is_the_question_and_what_led_to_it(
    async_db_session: AsyncSession,
) -> None:
    _, moment_id = await asked_a_question(async_db_session)

    run = await ask(async_db_session, moment_id, "agent", owner_user_id=None)

    assert "Can the CSV export ship this week?" in run.prompt
    assert "Dana: The usage report is late." in run.prompt
    assert run.prompt.index("usage report") < run.prompt.index("CSV export")


async def test_a_runner_claims_a_run_once_and_finishes_it(
    async_db_session: AsyncSession,
) -> None:
    _, moment_id = await asked_a_question(async_db_session)
    asked = await ask(async_db_session, moment_id, "agent", owner_user_id=None)

    claimed = await claim(async_db_session, None, ["agent"], runner="laptop")
    assert claimed is not None and claimed.id == asked.id
    assert (claimed.status, claimed.runner) == ("claimed", "laptop")
    assert await claim(async_db_session, None, ["agent"], runner="desk") is None

    done = await finish(
        async_db_session, claimed.id or 0, None, "It can.", ok=True, runner="laptop"
    )

    assert (done.status, done.result) == ("done", "It can.")
    assert done.finished_at is not None


async def test_only_what_claimed_a_run_finishes_it(
    async_db_session: AsyncSession,
) -> None:
    """Another of the owner's runners cannot post over a claimed run, nor
    over one the app is answering: the answer would be lost."""
    _, moment_id = await asked_a_question(async_db_session)
    await ask(async_db_session, moment_id, "agent", owner_user_id=None)
    claimed = await claim(async_db_session, None, ["agent"], runner="laptop")
    assert claimed is not None

    with pytest.raises(runs.RunNotFoundError):
        await finish(
            async_db_session, claimed.id or 0, None, "Not mine", ok=True, runner="desk"
        )

    done = await finish(
        async_db_session, claimed.id or 0, None, "It can.", ok=True, runner="laptop"
    )
    assert (done.status, done.result) == ("done", "It can.")


async def test_a_run_that_fails_says_why(async_db_session: AsyncSession) -> None:
    _, moment_id = await asked_a_question(async_db_session)
    await ask(async_db_session, moment_id, "agent", owner_user_id=None)
    claimed = await claim(async_db_session, None, ["agent"], runner="laptop")

    failed = await finish(
        async_db_session, claimed.id, None, "No repo", ok=False, runner="laptop"
    )  # type: ignore[union-attr, arg-type]

    assert (failed.status, failed.result) == ("failed", "No repo")


async def test_a_run_whose_runner_went_quiet_fails(
    async_db_session: AsyncSession,
) -> None:
    """A runner that died with its run, or a restart that took an in-app
    run with it, never finishes it; past its time it fails, so nothing
    waits on it."""
    _, moment_id = await asked_a_question(async_db_session)
    await ask(async_db_session, moment_id, "agent", owner_user_id=None)
    await ask(async_db_session, moment_id, "agent", owner_user_id=None)
    gone = await claim(async_db_session, None, ["agent"], runner="laptop")
    live = await claim(async_db_session, None, ["agent"], runner="desk")
    gone.claimed_at -= runs.ABANDONED_AFTER  # type: ignore[union-attr, operator]
    async_db_session.add(gone)
    await async_db_session.commit()

    assert await runs.fail_abandoned(async_db_session) == 1

    row = await async_db_session.get_one(MeetingMoment, moment_id)
    (moment,) = await moments_of(async_db_session, row.meeting_id)
    assert [(r.runner, r.status) for r in moment.runs] == [
        ("laptop", "failed"),
        ("desk", "claimed"),
    ]
    assert live is not None and moment.runs[0].result


async def test_a_runner_claims_only_its_owners_runs_and_its_actions(
    async_db_session: AsyncSession,
) -> None:
    """A runner holds one owner's token and names the actions it runs."""
    _, mine = await asked_a_question(async_db_session)
    await ask(async_db_session, mine, "agent", owner_user_id=None)

    assert await claim(async_db_session, None, ["other"], runner="laptop") is None
    assert await claim(async_db_session, None, ["agent"], runner="laptop") is not None


async def test_a_browser_action_is_not_asked(async_db_session: AsyncSession) -> None:
    """Copying happens in the browser: there is no run to make."""
    _, moment_id = await asked_a_question(async_db_session)

    with pytest.raises(ActionNotFoundError):
        await ask(async_db_session, moment_id, "copy", owner_user_id=None)
    with pytest.raises(ActionNotFoundError):
        await ask(async_db_session, moment_id, "nope", owner_user_id=None)


async def test_an_action_that_runs_in_the_app_finishes_on_its_own(
    async_db_session: AsyncSession,
    held: list[Awaitable[Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asked, it starts in the app at once; what it returns is its result,
    and what it raises is why it failed."""
    from tests._session import opens

    monkeypatch.setattr(runs, "get_async_session", opens(async_db_session))

    async def answer(prompt: str, owner_user_id: int | None) -> str:
        return "Yes, Thursday." if "CSV" in prompt else "?"

    _register(
        monkeypatch, Action("echo", "Echo", frozenset({"question"}), "app", run=answer)
    )
    _, moment_id = await asked_a_question(async_db_session)

    run = await ask(async_db_session, moment_id, "echo", owner_user_id=None)
    for started in held:
        await started

    await async_db_session.refresh(run)
    assert (run.status, run.result, run.runner) == ("done", "Yes, Thursday.", "app")


async def test_a_kind_can_ask_an_action_by_itself(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``MEETINGS_AUTO_ACTIONS`` names an action per kind: each new moment
    of that kind asks it, once, not again as its line grows."""
    monkeypatch.setattr(settings, "MEETINGS_AUTO_ACTIONS", "question=agent")
    _, moment_id = await asked_a_question(async_db_session)

    claimed = await claim(async_db_session, None, ["agent"], runner="laptop")

    assert claimed is not None and claimed.moment_id == moment_id
    assert await claim(async_db_session, None, ["agent"], runner="laptop") is None


async def test_an_action_registered_for_a_kind_is_offered_for_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register(
        monkeypatch,
        Action("ticket", "File a ticket", frozenset({"question"}), "runner"),
    )

    assert "ticket" in {a.name for a in registry.actions_for("question")}
    assert "ticket" not in {a.name for a in registry.actions_for("mention")}


def test_another_services_meeting_moments_module_registers_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A service adds actions (and detectors) in its ``meeting_moments``
    module, found on disk like its ``tools``, loaded before any is read."""
    from app.services.meetings.domains.moments import detectors

    def found(package: object, name: str) -> list[object]:
        assert name == "meeting_moments"
        _register(
            monkeypatch,
            Action("ticket", "File a ticket", frozenset({"question"}), "runner"),
        )
        return []

    monkeypatch.setattr(detectors, "import_modules_named", found)
    detectors.load_extensions.cache_clear()
    try:
        assert registry.action_named("ticket") is not None
    finally:
        detectors.load_extensions.cache_clear()


def _register(monkeypatch: pytest.MonkeyPatch, action: Action) -> None:
    """``action`` registered for the test only."""
    monkeypatch.setitem(registry._actions, action.name, action)


def test_an_action_is_registered_once() -> None:
    copy = registry.action_named("copy")

    with pytest.raises(ValueError):
        register_action(copy)  # type: ignore[arg-type]
