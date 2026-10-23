"""What a call threw up, in Overseer's meeting drawer: a tab per kind of
moment (Questions first), each with who said it and when, a button for
each action it offers (a browser action copies its prompt; the others are
asked), and what was asked of it; the drawer follows a run still going,
even once the call is over."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.web_frontend import overseer_meetings
from app.components.web_frontend.rendering import templates
from app.services.meetings.domains.actions.runs import claim, finish
from app.services.meetings.domains.moments import tidy
from app.services.meetings.domains.notes.queries import delete_in
from app.services.meetings.models import MeetingMoment, MeetingStatus
from app.services.meetings.service import MeetingsService
from app.services.system.models import ComponentStatus
from tests._meetings import (
    a_meeting,
    a_runner_looked_in,
    asked_a_question,
    hold_the_cleaner,
    said,
)
from tests.web.dom import none, one, select, text
from tests.web.overseer import page_html, sign_in, status_with

PARTIALS = overseer_meetings.PARTIALS
MEETINGS = ComponentStatus(name="meetings", message="Meetings ready")
HX = {"HX-Request": "true"}


@pytest.fixture
def overseer(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, async_client_with_db: TestClient
) -> TestClient:
    sign_in(app, monkeypatch, status_with(services=[MEETINGS]))
    return async_client_with_db


async def test_a_question_has_its_own_tab_with_what_can_be_done(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    meeting_id, moment_id = await asked_a_question(
        async_db_session, status=MeetingStatus.IN_CALL
    )

    html = page_html(overseer, f"{PARTIALS}/{meeting_id}/drawer")

    tabs = [text(t) for t in select(one(html, "[data-tabs]"), "[role=tab]")]
    assert "Questions" in tabs
    moment = one(html, f'[data-moment="{moment_id}"]')
    assert "Can the CSV export ship this week?" in text(moment)
    assert "Dana" in text(moment)
    copy = one(moment, "[data-copy]")
    assert text(copy) == "Copy for agent"
    assert "Can the CSV export ship this week?" in (copy.get("data-copy") or "")
    ask = one(moment, '[data-action="agent"]')
    assert ask.get("hx-post") == f"{PARTIALS}/{meeting_id}/moments/{moment_id}/runs"


async def test_an_action_asked_from_the_drawer_shows_where_it_stands(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """With no runner running, it says how to start one, and its button
    is not offered again while the run is out."""
    meeting_id, moment_id = await asked_a_question(
        async_db_session, status=MeetingStatus.IN_CALL
    )

    response = overseer.post(
        f"{PARTIALS}/{meeting_id}/moments/{moment_id}/runs",
        data={"action": "agent"},
        headers=HX,
    )

    assert response.status_code == 200, response.text
    run = one(response.text, f'[data-moment="{moment_id}"] [data-run]')
    assert "Ask agent" in text(run) and "meetings runner" in text(run)
    again = one(response.text, f'[data-moment="{moment_id}"] [data-action="agent"]')
    assert again.get("disabled") is not None


async def test_an_answer_shows_under_its_question_and_the_drawer_follows_until_then(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """The call is over, but a run asked of it is not: with a runner
    running, the drawer keeps reading itself until the answer is in, then
    stops."""
    meeting_id, moment_id = await asked_a_question(
        async_db_session, status=MeetingStatus.LEFT
    )
    await a_runner_looked_in(async_db_session)
    overseer.post(
        f"{PARTIALS}/{meeting_id}/moments/{moment_id}/runs",
        data={"action": "agent"},
        headers=HX,
    )

    waiting = page_html(overseer, f"{PARTIALS}/{meeting_id}/drawer")
    assert "every" in (one(waiting, "#meeting-body").get("hx-trigger") or "")

    run = await claim(async_db_session, None, ["agent"], runner="laptop")
    await finish(
        async_db_session,
        run.id or 0,  # type: ignore[union-attr]
        None,
        "Yes: export.py ships it.",
        ok=True,
        runner="laptop",
    )

    answered = page_html(overseer, f"{PARTIALS}/{meeting_id}/drawer")
    assert "Yes: export.py ships it." in text(one(answered, "[data-run]"))
    assert "laptop" in text(one(answered, "[data-run]"))
    assert not one(answered, "#meeting-body").get("hx-trigger")


async def test_a_question_folds_away_unless_it_is_being_answered(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """A long call's questions read as a list: each card folded to what was
    asked, open while something is answering it, its fold kept by name."""
    meeting_id, moment_id = await asked_a_question(
        async_db_session, status=MeetingStatus.LEFT
    )

    drawer = f"{PARTIALS}/{meeting_id}/drawer"
    folded = one(page_html(overseer, drawer), "[data-moment]")
    assert folded.tag == "details" and folded.get("open") is None
    assert folded.get("data-fold") == f"moment:{moment_id}"
    (summary,) = folded.cssselect("summary")
    assert "Can the CSV export ship this week?" in text(summary)

    await a_runner_looked_in(async_db_session)
    await MeetingsService(async_db_session, None).ask(meeting_id, moment_id, "agent")

    going = one(page_html(overseer, drawer), "[data-moment]")
    assert going.get("open") is not None


async def test_an_answer_reads_as_a_chat_reply_does(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """An answer is markdown, set in the typography a chat reply wears (in
    every stack, chat or not): its lists are lists, its paragraphs apart."""
    meeting_id, moment_id = await asked_a_question(
        async_db_session, status=MeetingStatus.LEFT
    )
    await a_runner_looked_in(async_db_session)
    await MeetingsService(async_db_session, None).ask(meeting_id, moment_id, "agent")
    run = await claim(async_db_session, None, ["agent"], runner="laptop")
    answer = "**Short answer:** yes.\n\n- `export.py` ships it.\n- Billing signed off."
    run_id: int = run.id  # type: ignore[union-attr,assignment]
    await finish(async_db_session, run_id, None, answer, ok=True, runner="laptop")

    html = page_html(overseer, f"{PARTIALS}/{meeting_id}/drawer")

    body = one(html, "[data-run] [data-answer]")
    prose = templates.env.get_template("components/macros/layout.html").module.prose
    assert body.get("class") == prose
    assert len(select(html, "[data-run] [data-answer] ul > li")) == 2


async def test_a_meeting_with_nothing_heard_has_no_questions_tab(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    meeting_id = await a_meeting(async_db_session)
    await said(async_db_session, meeting_id, ("Dana", "Hello."))  # type: ignore[arg-type]

    html = page_html(overseer, f"{PARTIALS}/{meeting_id}/drawer")

    none(html, "[data-moment]")
    assert "Questions" not in [text(t) for t in select(html, "[role=tab]")]


async def test_a_finished_call_is_read_over_again_from_the_drawer(
    overseer: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A call kept before its questions were looked for finds them from
    the transcript; one still under way has nothing to read over."""
    monkeypatch.setattr(tidy, "cleaner", lambda: None)
    meeting_id, _ = await asked_a_question(async_db_session, status=MeetingStatus.LEFT)
    await delete_in(async_db_session, MeetingMoment.meeting_id, [meeting_id])
    await async_db_session.commit()
    live, _ = await asked_a_question(async_db_session, status=MeetingStatus.IN_CALL)

    html = page_html(overseer, f"{PARTIALS}/{meeting_id}/drawer")
    look = one(html, "[data-look-over]")
    assert look.get("hx-post") == f"{PARTIALS}/{meeting_id}/moments/find"
    none(page_html(overseer, f"{PARTIALS}/{live}/drawer"), "[data-look-over]")

    found = overseer.post(f"{PARTIALS}/{meeting_id}/moments/find", headers=HX)

    assert found.status_code == 200, found.text
    assert "Questions" in [text(t) for t in select(found.text, "[role=tab]")]


async def test_a_look_over_cleans_up_in_the_background_and_the_drawer_follows(
    overseer: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model's pass over a call's questions takes a while: the drawer
    comes back at once and follows it until it is done."""
    cleaned, held = hold_the_cleaner(monkeypatch)
    meeting_id, _ = await asked_a_question(async_db_session, status=MeetingStatus.LEFT)

    found = overseer.post(f"{PARTIALS}/{meeting_id}/moments/find", headers=HX)

    assert found.status_code == 200, found.text
    assert not cleaned and "every 3s" in found.text
    await held.pop()
    assert cleaned == [meeting_id]
    done = page_html(overseer, f"{PARTIALS}/{meeting_id}/body")
    assert "every 3s" not in done


async def test_a_burst_of_questions_is_one_card(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """A question and its follow-up read as one, asked of together."""
    meeting_id = await a_meeting(async_db_session)
    await said(
        async_db_session,
        meeting_id,
        ("Dana", "Can the export ship this week?"),
        ("Dana", "Did billing sign off on it?"),
    )

    html = page_html(overseer, f"{PARTIALS}/{meeting_id}/drawer")

    (card,) = select(html, "[data-moment]")
    assert "export ship" in text(card) and "billing sign off" in text(card)
    assert len(select(card, "[data-also]")) == 1
