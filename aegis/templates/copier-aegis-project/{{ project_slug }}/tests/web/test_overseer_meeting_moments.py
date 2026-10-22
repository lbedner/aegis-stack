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
from app.services.meetings.domains.actions.runs import claim, finish
from app.services.meetings.models import MeetingStatus
from app.services.meetings.service import MeetingsService
from app.services.system.models import ComponentStatus
from tests._meetings import MEET, asked_a_question, said
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
    assert "Ask agent" in text(run) and "Waiting for a runner" in text(run)


async def test_an_answer_shows_under_its_question_and_the_drawer_follows_until_then(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """The call is over, but a run asked of it is not: the drawer keeps
    reading itself until the answer is in, then stops."""
    meeting_id, moment_id = await asked_a_question(
        async_db_session, status=MeetingStatus.LEFT
    )
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


async def test_a_meeting_with_nothing_heard_has_no_questions_tab(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    meeting = await MeetingsService(async_db_session, None).request(MEET, "Notes")
    await said(async_db_session, meeting.id, ("Dana", "Hello."))  # type: ignore[arg-type]

    html = page_html(overseer, f"{PARTIALS}/{meeting.id}/drawer")

    none(html, "[data-moment]")
    assert "Questions" not in [text(t) for t in select(html, "[role=tab]")]
