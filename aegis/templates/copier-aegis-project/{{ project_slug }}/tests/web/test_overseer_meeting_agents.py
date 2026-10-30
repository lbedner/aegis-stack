"""Overseer > Meetings > Agents: each Google account the bot joins as, who
it is, whether its sign-in still works, which meeting it is in now and its
card in a call (its picture, its camera); and the bot sent as one of them
from the Meetings page."""

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
from tests._meetings import MEET, PIXEL_PNG, hold_the_bot, signed_in_state
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


async def test_an_agents_card_is_set_from_its_row(
    overseer: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch)
    row = one(page_html(overseer, AGENTS), "#overseer-meeting-agents tbody tr")
    one(row, "form[data-agent-image] input[type=file]")
    assert one(row, "form[data-switch=camera] input").get("checked") is not None
    # A new agent answers only its owner.
    assert one(row, "form[data-switch=answers_anyone] input").get("checked") is None

    pictured = overseer.post(
        f"{PARTIALS}/agents/notetaker/image",
        files={"file": ("me.png", PIXEL_PNG, "image/png")},
        headers=HX,
    )
    off = overseer.post(f"{PARTIALS}/agents/notetaker/camera", headers=HX)
    anyone = overseer.post(
        f"{PARTIALS}/agents/notetaker/answers_anyone", data={"on": "on"}, headers=HX
    )

    assert pictured.status_code == 200, pictured.text
    image = one(pictured.text, "img[data-agent-image]")
    shown = overseer.get(image.get("src"))
    assert shown.content == PIXEL_PNG
    # Its address carries its version: a redraw never fetches it again.
    assert "?v=" in image.get("src")
    assert "immutable" in shown.headers["cache-control"]
    assert one(off.text, "form[data-switch=camera] input").get("checked") is None
    answering = one(anyone.text, "form[data-switch=answers_anyone] input")
    assert answering.get("checked") is not None


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>'


async def test_an_svg_is_a_picture_and_cannot_run_a_script(
    overseer: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch)

    overseer.post(
        f"{PARTIALS}/agents/notetaker/image",
        files={"file": ("me.svg", SVG, "image/svg+xml")},
        headers=HX,
    )
    shown = overseer.get(f"{PARTIALS}/agents/notetaker/image")

    assert shown.content == SVG
    assert "sandbox" in shown.headers["content-security-policy"]
    assert shown.headers["x-content-type-options"] == "nosniff"


async def test_a_picture_the_card_cannot_take_says_why_and_keeps_the_tab(
    overseer: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch)

    refused = overseer.post(
        f"{PARTIALS}/agents/notetaker/image",
        files={"file": ("notes.pdf", b"%PDF", "application/pdf")},
        headers=HX,
    )

    assert refused.status_code == 422
    one(refused.text, "#overseer-meeting-agents tbody tr")
    assert "application/pdf" in text(one(refused.text, "[role=alert]"))
