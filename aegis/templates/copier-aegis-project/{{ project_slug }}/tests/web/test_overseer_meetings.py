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
from app.services.meetings.domains.people.participants import keep_heard
from app.services.meetings.models import MeetingStatus, Notes
from app.services.meetings.service import MeetingsService, transition
from app.services.system.models import ComponentStatus
from tests._meetings import (
    MEET,
    THEIRS,
    docs_meeting,
    ended,
    hold_the_bot,
    hold_the_writer,
)
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


async def test_a_meeting_reads_as_its_calendar_names_it_and_its_link_is_offered(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """A row names the call as its calendar does, its link under it; one on
    no calendar reads as its link. The send form offers each link sent to
    before, once, newest first."""
    svc = MeetingsService(async_db_session, None)
    named = await svc.request(MEET, "Notes")
    named.title = "New Dev Call"
    async_db_session.add(named)
    await async_db_session.commit()
    other = "https://meet.google.com/zzz-zzzz-zzz"
    await svc.request(other, "Notes")
    await svc.request(MEET, "Notes")

    html = page_html(overseer, PAGE)

    cells = [
        text(c) for c in select(html, "#overseer-meetings tbody tr td:first-child")
    ]
    assert any("New Dev Call" in c and MEET in c for c in cells)
    assert other in cells
    offered = [o.get("value") for o in select(html, "datalist#meeting-links option")]
    assert offered == [MEET, other]


async def test_the_admin_sees_every_owners_meetings(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    mine = await _ended(async_db_session, None)
    theirs = await _ended(async_db_session, THEIRS)

    rows = select(page_html(overseer, PAGE), "#overseer-meetings tbody tr")

    links = [one(row, "a").get("href") for row in rows]
    assert any(f"meeting={mine}" in link for link in links)
    assert any(f"meeting={theirs}" in link for link in links)


async def test_a_row_opens_its_notes_and_transcript_in_the_drawer(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    meeting_id = await _ended(async_db_session, None)
    await keep_heard(async_db_session, meeting_id, {"Ada": 42.0})

    page = page_html(overseer, f"{PAGE}?meeting={meeting_id}")
    sync = one(page, "[data-drawer-sync]")
    assert sync.get("data-drawer-url") == f"{PARTIALS}/{meeting_id}/drawer"
    html = page_html(overseer, f"{PARTIALS}/{meeting_id}/drawer")

    assert "Ada's summary." in text(one(html, "#meeting-summary"))
    assert "Ada said this." in text(one(html, "#meeting-transcript"))
    assert "Ada" in text(one(html, "#meeting-heard"))
    assert one(html, "[hx-get$='/confirm-delete']") is not None
    none(html, "[data-leave]")


def _tabs(html: str) -> tuple[list[str], list[str]]:
    """The drawer's tabs, and the panels shown (the rest hidden)."""
    tabs = one(html, "[data-tabs]")
    panels = select(tabs, "[data-tab-panel]")
    return (
        [text(tab) for tab in select(tabs, "[role=tab]")],
        [p.get("data-tab-panel") or "" for p in panels if p.get("hidden") is None],
    )


async def test_a_long_call_is_read_a_tab_at_a_time(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """Notes first; a search hit opens on the transcript, at its line."""
    meeting_id, ids = await ended(
        async_db_session,
        None,
        ("Ada", "Ada said this."),
        notes=lambda _: Notes(summary="-"),
    )
    await keep_heard(async_db_session, meeting_id, {"Ada": 42.0})

    drawer = page_html(overseer, f"{PARTIALS}/{meeting_id}/drawer")
    at_hit = page_html(overseer, f"{PARTIALS}/{meeting_id}/drawer?line={ids[0]}")

    assert _tabs(drawer) == (
        ["Notes", "Threads", "Transcript", "Who talked"],
        ["notes"],
    )
    assert _tabs(at_hit)[1] == ["transcript"]


async def test_a_meeting_the_bot_left_reads_as_done_not_greyed_out(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """The bot leaves when the call ends: that is how a meeting goes well."""
    meeting_id = await _ended(async_db_session, None)

    html = page_html(overseer, f"{PARTIALS}/{meeting_id}/drawer")

    assert one(html, "[data-status] [data-tone]").get("data-tone") == "ok"


async def test_deleting_a_meeting_from_the_drawer(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    meeting_id = await _ended(async_db_session, THEIRS)

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
    await keep_heard(
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
