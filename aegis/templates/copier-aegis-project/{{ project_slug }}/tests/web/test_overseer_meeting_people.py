"""Overseer > Meetings > People: how to work with each person who speaks
in the meetings, every owner's for the admin. A row opens one guide in the
drawer, each point with the lines it rests on; the owner's note is kept
from there and the guide written again."""

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.web_frontend import overseer_meetings
from app.services.meetings.domains.people import service as people_service
from app.services.meetings.models import NoteItem, Notes
from app.services.system.models import ComponentStatus
from tests._meetings import ended, kept_guide
from tests.web.dom import none, one, select, text
from tests.web.overseer import page_html, sign_in, status_with

PEOPLE = f"{overseer_meetings.PAGE}/people"
PARTIALS = f"{overseer_meetings.PARTIALS}/people"
MEETINGS = ComponentStatus(name="meetings", message="Meetings ready")
HX = {"HX-Request": "true"}


@pytest.fixture
def overseer(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, async_client_with_db: TestClient
) -> TestClient:
    """Signed in as an admin, on the test's own session."""
    sign_in(app, monkeypatch, status_with(services=[MEETINGS]))
    return async_client_with_db


@pytest.fixture
def held(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """A model to write guides with, its runs held rather than started."""
    runs: list[Any] = []

    async def write(person_id: int) -> None:
        return None

    monkeypatch.setattr(people_service, "guide_writer", lambda: write)
    monkeypatch.setattr(people_service, "background", runs.append)
    monkeypatch.setattr(people_service, "GUIDING", set())
    return runs


async def test_every_owners_people_are_listed(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    mine = await kept_guide(async_db_session, None, "Ada")
    theirs = await kept_guide(async_db_session, 4242, "Grace")

    rows = select(page_html(overseer, PEOPLE), "#overseer-meeting-people tbody tr")

    links = [one(row, "a").get("href") for row in rows]
    assert any(f"person={mine}" in link for link in links)
    assert any(f"person={theirs}" in link for link in links)


async def test_a_guide_opens_with_the_lines_each_point_rests_on(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    meeting_id, ids = await ended(
        async_db_session,
        4242,
        ("Ada", "Numbers first, then the story."),
        notes=lambda _: Notes(summary="-"),
    )
    guide_id = await kept_guide(
        async_db_session,
        4242,
        "Ada",
        information=[NoteItem(text="Wants the numbers first", lines=ids)],
    )

    page = page_html(overseer, f"{PEOPLE}?person={guide_id}")
    sync = one(page, "[data-drawer-sync]")
    assert sync.get("data-drawer-url") == f"{PARTIALS}/{guide_id}/drawer"
    html = page_html(overseer, f"{PARTIALS}/{guide_id}/drawer")

    facts = {text(dt): text(dt.getnext()) for dt in select(html, "dl dt")}
    assert facts["Owner"] == "4242"
    part = one(html, '[data-guide-section="information"]')
    assert "Wants the numbers first" in text(part)
    # The lines fold under the point, closed until it is opened.
    lines = one(part, "details[data-quotes]")
    assert lines.get("open") is None
    quote = one(lines, "[data-quote]")
    assert "Numbers first, then the story." in text(quote)
    assert f"meeting={meeting_id}" in (one(quote, "a").get("href") or "")


async def test_the_owners_note_is_kept_from_the_drawer(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    guide_id = await kept_guide(async_db_session, 4242, "Ada")

    response = overseer.post(
        f"{PARTIALS}/{guide_id}/note", data={"note": "Calls, not email."}, headers=HX
    )

    assert response.status_code == 200, response.text
    assert text(one(response.text, "textarea[name=note]")) == "Calls, not email."
    reread = page_html(overseer, f"{PARTIALS}/{guide_id}/drawer")
    assert text(one(reread, "textarea[name=note]")) == "Calls, not email."


async def test_a_guide_is_written_again_from_the_drawer(
    overseer: TestClient, async_db_session: AsyncSession, held: list[Any]
) -> None:
    guide_id = await kept_guide(async_db_session, 4242, "Ada")
    html = page_html(overseer, f"{PARTIALS}/{guide_id}/drawer")
    one(html, "[data-write-guide]")

    response = overseer.post(f"{PARTIALS}/{guide_id}/guide", headers=HX)

    assert response.status_code == 200, response.text
    body = one(response.text, "#guide-body")
    assert body.get("hx-trigger") == "every 3s"
    none(response.text, "[data-write-guide]")
    for run in held:
        await run


async def test_without_a_model_there_is_nothing_to_write_with(
    overseer: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(people_service, "guide_writer", lambda: None)
    guide_id = await kept_guide(async_db_session, 4242, "Ada")

    none(page_html(overseer, f"{PARTIALS}/{guide_id}/drawer"), "[data-write-guide]")
    assert overseer.post(f"{PARTIALS}/{guide_id}/guide", headers=HX).status_code == 409
