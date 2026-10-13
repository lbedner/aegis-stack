"""The Overseer Meetings page: every owner's meetings for the admin, one
opening in the drawer with its notes and transcript, asked to leave or
deleted from there. Reads and writes go through ``MeetingsService`` on
the request's session, unscoped (the admin sees every owner's)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.web_frontend import overseer_meetings
from app.services.meetings.models import MeetingStatus, Notes
from app.services.meetings.service import MeetingsService, save_heard, transition
from app.services.system.models import ComponentStatus
from tests._meetings import MEET, ended
from tests.web.dom import none, one, select, text
from tests.web.overseer import page_html, sign_in, status_with

PAGE = overseer_meetings.PAGE
PARTIALS = overseer_meetings.PARTIALS
MEETINGS = ComponentStatus(name="meetings", message="Meetings ready")


@pytest.fixture
def overseer(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, async_client_with_db: TestClient
) -> TestClient:
    """Signed in as an admin, on the test's own session."""
    sign_in(app, monkeypatch, status_with(services=[MEETINGS]))
    return async_client_with_db


async def _ended(session: AsyncSession, owner: int | None) -> int:
    """A meeting of ``owner``'s the bot has left, with a line and notes."""
    meeting_id, _ = await ended(
        session,
        owner,
        ("Ada", "Ada said this."),
        notes=lambda _: Notes(summary="Ada's summary."),
    )
    return meeting_id


async def test_the_admin_sees_every_owners_meetings(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    mine = await _ended(async_db_session, None)
    theirs = await _ended(async_db_session, 4242)

    rows = select(page_html(overseer, PAGE), "#overseer-meetings tbody tr")

    links = [one(row, "a").get("href") for row in rows]
    assert any(f"meeting={mine}" in link for link in links)
    assert any(f"meeting={theirs}" in link for link in links)


async def test_a_row_opens_its_notes_and_transcript_in_the_drawer(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    meeting_id = await _ended(async_db_session, None)
    await save_heard(async_db_session, meeting_id, {"Ada": 42.0})

    page = page_html(overseer, f"{PAGE}?meeting={meeting_id}")
    sync = one(page, "[data-drawer-sync]")
    assert sync.get("data-drawer-url") == f"{PARTIALS}/{meeting_id}/drawer"
    html = page_html(overseer, f"{PARTIALS}/{meeting_id}/drawer")

    assert "Ada's summary." in text(one(html, "#meeting-summary"))
    assert "Ada said this." in text(one(html, "#meeting-transcript"))
    assert "Ada 42s" in html
    assert one(html, "[hx-get$='/confirm-delete']") is not None
    none(html, "[data-leave]")


async def test_deleting_a_meeting_from_the_drawer(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    meeting_id = await _ended(async_db_session, 4242)

    confirm = page_html(overseer, f"{PARTIALS}/{meeting_id}/confirm-delete")
    assert "transcript" in text(one(confirm, "p"))
    assert overseer.delete(f"{PARTIALS}/{meeting_id}").status_code == 204

    assert overseer.get(f"{PARTIALS}/{meeting_id}/drawer").status_code == 404


async def test_a_meeting_the_bot_is_in_is_asked_to_leave_not_deleted(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    meeting = await MeetingsService(async_db_session, None).request(MEET)
    await transition(
        async_db_session,
        meeting.id,  # type: ignore[arg-type]
        MeetingStatus.IN_CALL,
        from_=(MeetingStatus.REQUESTED,),
    )

    html = page_html(overseer, f"{PARTIALS}/{meeting.id}/drawer")
    assert one(html, "[data-leave]") is not None
    none(html, "[hx-get$='/confirm-delete']")
    assert overseer.delete(f"{PARTIALS}/{meeting.id}").status_code == 409
    assert overseer.post(f"{PARTIALS}/{meeting.id}/leave").status_code == 200

    left = await MeetingsService(async_db_session, None).get(meeting.id)  # type: ignore[arg-type]
    assert left.status == MeetingStatus.LEAVING
