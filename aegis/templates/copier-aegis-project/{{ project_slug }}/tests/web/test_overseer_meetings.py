"""The Overseer Meetings page: every owner's meetings for the admin, the
bot sent from there, one opening in the drawer with everything the
Meetings page has (live while the bot is in, which speaker is me, the
notes written again), asked to leave or deleted from there. Reads and writes go through ``MeetingsService`` on
the request's session, unscoped (the admin sees every owner's)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.web_frontend import overseer_meetings
from app.services.meetings.models import MeetingStatus, Notes
from app.services.meetings.service import MeetingsService, save_heard, transition
from app.services.system.models import ComponentStatus
from tests._meetings import MEET, docs_meeting, ended, hold_the_bot, hold_the_writer
from tests.web.dom import location, none, one, select, text
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
    assert "Ada" in text(one(html, "#meeting-heard"))
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


HX = {"HX-Request": "true"}


def test_the_admin_sends_the_bot_from_overseer(
    overseer: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """From Overseer's own Meetings page; its meeting opens in the drawer."""
    sent = hold_the_bot(monkeypatch)
    form = one(page_html(overseer, PAGE), "form[data-send]")
    assert form.get("hx-post") == PARTIALS

    response = overseer.post(
        PARTIALS, data={"url": MEET, "bot_name": "Notes"}, headers=HX
    )

    assert response.status_code == 200, response.text
    assert location(response) == f"{PAGE}?meeting={sent[0]}"
    refused = overseer.post(PARTIALS, data={"url": "https://example.com/x"}, headers=HX)
    assert refused.status_code == 422
    assert len(sent) == 1


async def test_the_drawer_follows_a_meeting_the_bot_is_in(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    meeting = await MeetingsService(async_db_session, None).request(MEET)
    body_url = f"{PARTIALS}/{meeting.id}/body"

    drawer = page_html(overseer, f"{PARTIALS}/{meeting.id}/drawer")

    live = one(drawer, "#meeting-body")
    assert live.get("hx-get") == body_url and "every" in live.get("hx-trigger")
    assert "every" in one(page_html(overseer, body_url), "#meeting-body").get(
        "hx-trigger"
    )


async def test_from_the_drawer_the_admin_says_who_they_are_and_rewrites_notes(
    overseer: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, runs = hold_the_writer(monkeypatch)
    meeting_id = await docs_meeting(async_db_session, None)
    base = f"{PARTIALS}/{meeting_id}"

    drawer = page_html(overseer, f"{base}/drawer")
    assert one(drawer, "#my-items form").get("hx-post") == f"{base}/me"
    assert one(drawer, f'[hx-post="{base}/notes"]') is not None

    picked = overseer.post(f"{base}/me", data={"name": "Ada"}, headers=HX)
    assert "Write the docs" in text(one(picked.text, "#my-items"))
    rewritten = overseer.post(f"{base}/notes", headers=HX)
    assert "Writing the notes" in text(one(rewritten.text, "#meeting-notes"))
    await runs[0]
    assert started == [meeting_id]


async def test_who_talked_and_for_how_long_reads_as_a_list(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """Most first, as the house's ranked rows: each speaker marked in their
    color, a bar against the most heard; audio no caption explained is
    Unknown, unmarked."""
    meeting_id, _ = await ended(
        async_db_session,
        None,
        ("William Ferro", "So here it is."),
        ("Lisa Atalese", "Okay."),
        notes=lambda _: Notes(summary="Shown."),
    )
    await save_heard(
        async_db_session,
        meeting_id,
        {"Lisa Atalese": 465.0, "William Ferro": 3025.0, "Unknown": 627.0},
    )

    html = page_html(overseer, f"{PARTIALS}/{meeting_id}/drawer")

    rows = select(html, "#meeting-heard li")
    assert [text(row) for row in rows] == [
        "William Ferro 50m 25s",
        "Unknown 10m 27s",
        "Lisa Atalese 7m 45s",
    ]
    assert "--aegis-chart-" in one(rows[0], "[data-dot]").get("style")
    none(rows[1], "[data-dot]")
