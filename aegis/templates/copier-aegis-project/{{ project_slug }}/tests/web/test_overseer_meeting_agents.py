"""Overseer > Meetings > Agents: each Google account the bot joins as, who
it is, whether its sign-in still works and which meeting it is in now; and
the bot sent as one of them from the Meetings page."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.web_frontend import overseer_meetings
from app.services.meetings.domains.accounts.service import keep_agent
from app.services.meetings.models import MeetingStatus
from app.services.meetings.service import MeetingsService, transition
from app.services.system.models import ComponentStatus
from tests._meetings import MEET, hold_the_bot, signed_in_state
from tests._secret_settings import use_store
from tests.web.dom import location, none, one, select, text
from tests.web.overseer import page_html, sign_in, status_with

PAGE = overseer_meetings.PAGE
AGENTS = f"{PAGE}/agents"
PARTIALS = overseer_meetings.PARTIALS
MEETINGS = ComponentStatus(name="meetings", message="Meetings ready")
HX = {"HX-Request": "true"}
SIGNED_IN = signed_in_state()


@pytest.fixture
def overseer(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, async_client_with_db: TestClient
) -> TestClient:
    """Signed in as an admin, on the test's own session."""
    sign_in(app, monkeypatch, status_with(services=[MEETINGS]))
    return async_client_with_db


async def test_each_agent_says_who_it_is_its_sign_in_and_where_it_is(
    overseer: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = use_store(monkeypatch)
    work = await keep_agent(async_db_session, "work", "Work Notes", "w@work.example")
    store.values[work.login_secret] = json.dumps(SIGNED_IN)
    meeting = await MeetingsService(async_db_session, None).request(
        MEET, "Work Notes", work.id
    )
    await transition(
        async_db_session,
        meeting.id,  # type: ignore[arg-type]
        MeetingStatus.IN_CALL,
        from_=(MeetingStatus.REQUESTED,),
    )

    rows = select(page_html(overseer, AGENTS), "#overseer-meeting-agents tbody tr")

    shown = {text(row).split()[0]: row for row in rows}
    assert set(shown) == {"notetaker", "work"}
    assert "w@work.example" in text(shown["work"])
    assert "Signed in" in text(shown["work"])
    assert "Not signed in" in text(shown["notetaker"])
    link = one(shown["work"], "a[data-in-now]")
    assert link.get("href") == f"{PAGE}?meeting={meeting.id}"
    none(shown["notetaker"], "a[data-in-now]")


async def test_the_bot_is_sent_as_the_agent_picked(
    overseer: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_store(monkeypatch)
    sent = hold_the_bot(monkeypatch)
    work = await keep_agent(async_db_session, "work", "Work Notes", None)
    page = page_html(overseer, PAGE)
    picked = [o.get("value") for o in select(page, "form[data-send] select option")]
    assert picked == ["notetaker", "work"]

    response = overseer.post(PARTIALS, data={"url": MEET, "agent": "work"}, headers=HX)

    assert response.status_code == 200, response.text
    assert location(response) == f"{PAGE}?meeting={sent[0]}"
    meeting = await MeetingsService(async_db_session, None).get(sent[0])
    assert meeting.account_id == work.id
    rows = select(page_html(overseer, PAGE), "#overseer-meetings tbody tr")
    assert "work" in text(rows[0])


async def test_with_one_agent_there_is_nothing_to_pick(
    overseer: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch)

    none(page_html(overseer, PAGE), "form[data-send] select")
