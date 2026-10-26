"""Actions: what can be done with a moment. Each is registered by name with
the kinds of moment it takes and where it runs: in the browser (copied),
in the app, or on a runner on another machine. Asking one makes a run,
claimed once by what runs it and finished with what it came back with."""

from collections.abc import Awaitable
from importlib.util import find_spec
from typing import Any

import pytest
from sqlmodel import select
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
from app.services.meetings.models import MeetingActionRun, MeetingMoment
from tests._meetings import (
    FakeLive,
    a_meeting,
    a_runner_looked_in,
    asked_a_question,
    said,
    topic,
)

# Ask AI (``ask_ai``) renders only with the AI service on pydantic-ai and a
# database.
needs_her = pytest.mark.skipif(
    find_spec("app.services.meetings.domains.actions.ask_ai") is None,
    reason="this stack has no Ask AI",
)


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


async def test_asking_again_while_it_runs_is_the_same_run(
    async_db_session: AsyncSession,
) -> None:
    """A second click while the first is still going asks nothing new; once
    it is done, asking again does."""
    _, moment_id = await asked_a_question(async_db_session)

    first = await ask(async_db_session, moment_id, "agent", owner_user_id=None)
    again = await ask(async_db_session, moment_id, "agent", owner_user_id=None)
    assert again.id == first.id
    claimed = await claim(async_db_session, None, ["agent"], runner="laptop")
    await finish(
        async_db_session, claimed.id or 0, None, "Done.", ok=True, runner="laptop"
    )  # type: ignore[union-attr]

    later = await ask(async_db_session, moment_id, "agent", owner_user_id=None)
    assert (later.status, later.result) == ("asked", None)


async def test_asking_again_keeps_only_the_latest_answer(
    async_db_session: AsyncSession,
) -> None:
    """One answer per action per moment: asking again once it is back
    replaces it, so a moment never piles up old answers."""
    meeting_id, moment_id = await asked_a_question(async_db_session)
    first = await ask(async_db_session, moment_id, "agent", owner_user_id=None)
    await claim(async_db_session, None, ["agent"], runner="laptop")
    await finish(
        async_db_session, first.id or 0, None, "Old.", ok=True, runner="laptop"
    )

    later = await ask(async_db_session, moment_id, "agent", owner_user_id=None)

    (moment,) = await moments_of(async_db_session, meeting_id)
    assert [r.id for r in moment.runs] == [later.id]


async def test_a_run_waits_on_a_runner_only_while_one_is_listening(
    async_db_session: AsyncSession,
) -> None:
    """Asked of a runner while none is running, a run says so and the page
    does not keep reading itself for it; once a runner has looked in, it
    waits for it. Either way its button is busy."""
    from app.services.meetings.domains.moments.service import answering

    meeting_id, moment_id = await asked_a_question(async_db_session)
    await ask(async_db_session, moment_id, "agent", owner_user_id=None)

    (alone,) = await moments_of(async_db_session, meeting_id)
    (run,) = alone.runs
    assert not run.going and "No runner" in run.state
    assert not answering([alone])
    assert {a.name: a.busy for a in alone.actions}["agent"]

    await a_runner_looked_in(async_db_session)

    (watched,) = await moments_of(async_db_session, meeting_id)
    assert watched.runs[0].state == "Waiting for a runner"
    assert answering([watched])


async def test_asking_any_question_of_a_burst_asks_them_all(
    async_db_session: AsyncSession,
) -> None:
    """The run is the burst's, kept on its first question, its prompt
    every question in it and what was said between them."""
    from app.services.meetings.domains.moments import service as moments

    meeting_id = await a_meeting(async_db_session)
    lines = await said(
        async_db_session,
        meeting_id,
        ("Dana", "Can the export ship this week?"),
        ("Tom", "It depends on billing."),
        ("Dana", "Did billing sign off on it?"),
    )
    (led,) = await moments_of(async_db_session, meeting_id)
    (follow,) = led.also

    run = await moments.ask(async_db_session, meeting_id, follow.id, "agent", None)

    assert run.moment_id == led.id and led.line_id == lines[0]
    assert "export ship" in run.prompt and "billing sign off" in run.prompt
    assert "It depends on billing." in run.prompt


async def test_a_burst_asked_by_itself_is_asked_once(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``MEETINGS_AUTO_ACTIONS`` asks a card, not each question in it: a
    follow-up said while the first is being answered is that run."""
    monkeypatch.setattr(settings, "MEETINGS_AUTO_ACTIONS", "question=agent")
    meeting_id = await a_meeting(async_db_session)
    await said(
        async_db_session,
        meeting_id,
        ("Dana", "Can the export ship this week?"),
        ("Dana", "Did billing sign off on it?"),
    )

    (card,) = await moments_of(async_db_session, meeting_id)
    assert len(card.runs) == 1


async def test_a_card_keeps_one_answer_whichever_question_it_was_on(
    async_db_session: AsyncSession,
) -> None:
    """Cards merge by topic once a call is cleaned up, bringing each
    question's earlier answer with them: asking the card again replaces
    them all, and one still going on any of them is that run."""
    from app.services.meetings.domains.moments import service as moments

    meeting_id = await a_meeting(async_db_session)
    await said(
        async_db_session,
        meeting_id,
        ("Dana", "How do members return a scale?"),
        ("Tom", "What does the assistant say on returns?"),
        apart=600.0,
    )
    first, second = await moments_of(async_db_session, meeting_id)
    earlier = MeetingActionRun(
        moment_id=second.id, action="agent", prompt="?", status="done", result="Old."
    )
    async_db_session.add(earlier)
    await topic(async_db_session, [first.id, second.id], "Scale returns")

    run = await moments.ask(async_db_session, meeting_id, first.id, "agent", None)
    again = await moments.ask(async_db_session, meeting_id, second.id, "agent", None)

    (card,) = await moments_of(async_db_session, meeting_id)
    assert [r.id for r in card.runs] == [run.id] and again.id == run.id


async def test_a_card_asked_across_a_long_call_reads_only_what_it_needs(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A topic card's questions can sit an hour apart: its prompt is them
    and what led to the first, read without the whole call between."""
    from app.services.meetings.domains.actions import prompt
    from app.services.meetings.domains.moments import service as moments

    meeting_id = await a_meeting(async_db_session)
    chatter = [("Tom", f"Status item {n}.") for n in range(3 * prompt.CONTEXT_LINES)]
    await said(
        async_db_session,
        meeting_id,
        ("Dana", "Returns are up this month."),
        ("Dana", "How do members return a scale?"),
        *chatter,
        ("Tom", "What does the assistant say on returns?"),
        apart=60.0,
    )
    first, second = await moments_of(async_db_session, meeting_id)
    await topic(async_db_session, [first.id, second.id], "Scale returns")
    read: list[int] = []
    real = prompt.moments_queries.said

    async def counted(*args: Any, **kwargs: Any) -> list[tuple[str, int, str]]:
        rows = await real(*args, **kwargs)
        read.append(len(rows))
        return rows

    monkeypatch.setattr(prompt.moments_queries, "said", counted)

    run = await moments.ask(async_db_session, meeting_id, first.id, "agent", None)

    assert "Returns are up this month." in run.prompt
    assert "return a scale" in run.prompt and "assistant say" in run.prompt
    assert "Status item 0." not in run.prompt
    assert max(read) <= 2 * prompt.CONTEXT_LINES + 1


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
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A runner that died with its run, or a restart that took an in-app
    run with it, never finishes it; past its time it fails, so nothing
    waits on it."""
    _register(
        monkeypatch,
        Action("ticket", "File a ticket", frozenset({"question"}), "runner"),
    )
    _, moment_id = await asked_a_question(async_db_session)
    await ask(async_db_session, moment_id, "agent", owner_user_id=None)
    await ask(async_db_session, moment_id, "ticket", owner_user_id=None)
    gone = await claim(async_db_session, None, ["agent"], runner="laptop")
    live = await claim(async_db_session, None, ["ticket"], runner="desk")
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


@needs_her
async def test_a_question_put_to_the_bot_is_answered_by_her_unasked(
    async_db_session: AsyncSession,
    held: list[Awaitable[Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Named, she answers: no setting asks it. She is asked as herself,
    Overseer's own agent (her prompt, her tools), with the meeting so far,
    in a conversation of the meetings' own."""
    from types import SimpleNamespace

    from app.services.meetings.domains.actions import ask_ai
    from tests._session import opens

    monkeypatch.setattr(runs, "get_async_session", opens(async_db_session))
    asked: list[tuple[str, dict[str, Any]]] = []

    class Her:
        async def chat(self, message: str, **kwargs: Any) -> Any:
            asked.append((message, kwargs))
            return SimpleNamespace(content="Sam owns billing.")

    monkeypatch.setattr(ask_ai, "her", Her)
    meeting_id = await a_meeting(async_db_session)  # the bot joins as "Notes"
    await said(
        async_db_session,
        meeting_id,
        ("Dana", "The invoices went out late again."),
        ("Dana", "Hey Notes, who owns billing?"),
    )
    for started in held:
        await started

    (run,) = (await async_db_session.exec(select(MeetingActionRun))).all()
    assert (run.action, run.status, run.result) == ("ai", "done", "Sam owns billing.")
    message, how = asked[0]
    assert "The invoices went out late again." in message
    assert "who owns billing?" in message
    assert how["agent_slug"] is None and how["surface"] == "meetings"


@needs_her
def test_ask_ai_answers_a_question_and_a_question_put_to_her() -> None:
    assert "ai" in {a.name for a in registry.actions_for("question")}
    assert "ai" in {a.name for a in registry.actions_for("addressed")}


def test_a_line_put_to_the_bot_offers_what_a_question_does() -> None:
    """Put to her by name, it is still a question a coding agent can take."""
    names = {action.name for action in registry.actions_for("addressed")}

    assert {"copy", "agent"} <= names


@needs_her
def test_what_answers_her_unasked_is_hers_unless_a_setting_names_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One choice, read by the moments and by the bot in the call alike:
    hers, else a setting's; none where the stack has nothing to answer."""
    from app.services.meetings.domains.moments.service import answerer

    assert answerer() == registry.ANSWERS
    monkeypatch.setattr(settings, "MEETINGS_AUTO_ACTIONS", "addressed=agent")
    assert answerer() == "agent"
    monkeypatch.setattr(settings, "MEETINGS_AUTO_ACTIONS", "addressed=copy")
    assert answerer() is None  # copied by a person, never answered
    monkeypatch.setattr(settings, "MEETINGS_AUTO_ACTIONS", "")
    monkeypatch.delitem(registry._actions, registry.ANSWERS)  # no AI here
    assert answerer() is None


@needs_her
async def test_in_a_call_with_her_live_voice_she_answers_through_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live, her answer is made and heard in the call at once; once the
    live call fails, or is over, she answers as she did, in a chat turn."""
    from types import SimpleNamespace

    from app.services.meetings.domains.actions import ask_ai
    from app.services.meetings.domains.actions.live import LIVE

    class Her:
        async def chat(self, message: str, **kwargs: Any) -> Any:
            return SimpleNamespace(content="From the chat.")

    monkeypatch.setattr(ask_ai, "her", Her)
    live = FakeLive("Said live.")
    token = LIVE.set(live)
    try:
        assert await ask_ai.answer("Who owns billing?", None) == "Said live."
        assert live.asked == ["Who owns billing?"]
        LIVE.set(FakeLive(RuntimeError("Her live call ended")))
        assert await ask_ai.answer("Who owns billing?", None) == "From the chat."
        LIVE.set(FakeLive("Said live.", open=False))
        assert await ask_ai.answer("Who owns billing?", None) == "From the chat."
    finally:
        LIVE.reset(token)


@needs_her
async def test_her_live_call_is_told_only_what_it_has_not_heard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One call lasts the meeting and holds every question put to it, and
    what led to each: sent again, each answer would cost more than the
    last. Each question after the first carries only the lines since."""
    from app.services.meetings.domains.actions import ask_ai
    from app.services.meetings.domains.actions.live import LIVE
    from app.services.meetings.domains.actions.prompt import Excerpt

    first = Excerpt("addressed", "", "Dana", "who owns billing?", [("Sam", "Late.")])
    then = Excerpt(
        "addressed",
        "",
        "Dana",
        "and search?",
        [("Sam", "Late."), ("Dana", "who owns billing?"), ("Sam", "Search is mine.")],
    )
    live = FakeLive("Sam does.")
    token = LIVE.set(live)
    try:
        await ask_ai.answer(ask_ai.for_the_model(first), None)
        await ask_ai.answer(ask_ai.for_the_model(then), None)
    finally:
        LIVE.reset(token)

    assert "Late." in live.asked[0]
    assert "Late." not in live.asked[1] and "Search is mine." in live.asked[1]
    assert "and search?" in live.asked[1]


# Two runs, each reading its moment and meeting: a loop by construction.
@pytest.mark.queryspy(allow_n_plus_one=True)
async def test_only_a_line_put_to_her_by_name_is_answered_aloud(
    async_db_session: AsyncSession,
    held: list[Awaitable[Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In a call with her live voice, a question asked of an action in the
    app (a setting asking Ask AI of every question, say) is not said aloud
    in the call: only a line put to her by name is."""
    from app.services.meetings.domains.actions.live import LIVE
    from app.services.meetings.domains.moments import service as moments_service
    from tests._session import opens

    heard: list[Any] = []

    async def probe(prompt: str, owner_user_id: int | None) -> str:
        heard.append(LIVE.get())
        return "Done."

    monkeypatch.setitem(
        registry._actions,
        "probe",
        Action("probe", "Probe", registry.QUESTIONS, "app", run=probe),
    )
    monkeypatch.setattr(moments_service, "answerer", lambda: None)  # none asked
    monkeypatch.setattr(runs, "get_async_session", opens(async_db_session))
    meeting_id = await a_meeting(async_db_session)  # the bot joins as "Notes"
    await said(
        async_db_session,
        meeting_id,
        ("Dana", "Can the CSV export ship this week?"),
        ("Dana", "Hey Notes, who owns billing?"),
    )
    asked, put_to_her = await moments_of(async_db_session, meeting_id)
    token = LIVE.set(FakeLive("Said live."))
    try:
        for moment in (asked, put_to_her):
            await runs.ask(
                async_db_session, moment.id or 0, "probe", owner_user_id=None
            )
        for started in held:
            await started
    finally:
        LIVE.reset(token)

    assert (asked.kind, put_to_her.kind) == ("question", "addressed")
    assert heard[0] is None and heard[1] is not None
