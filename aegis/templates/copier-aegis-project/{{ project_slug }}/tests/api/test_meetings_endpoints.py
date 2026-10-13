"""Meetings over HTTP: asking the bot into a call starts it in the
background and answers at once; the meeting is then read back, and the bot
asked to leave. Through ``authenticated_app_client`` so the suite runs with
and without the auth service."""

from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.models import MeetingStatus, Notes
from app.services.meetings.service import MeetingsService, save_heard, transition
from tests._audit import as_admin
from tests._meetings import MEET, docs_meeting, ended, hold_the_bot, hold_the_writer

ADMIN = "/api/v1/meetings/admin"


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The meetings the bot was started on, without starting it."""
    return hold_the_bot(monkeypatch)


def test_asking_the_bot_in_starts_it_and_answers_at_once(
    authenticated_app_client: TestClient, started: list[int]
) -> None:
    response = authenticated_app_client.post(
        "/api/v1/meetings", json={"url": MEET, "bot_name": "Notes"}
    )

    assert response.status_code == 202, response.text
    meeting = response.json()
    assert meeting["status"] == "requested" and meeting["bot_name"] == "Notes"
    assert started == [meeting["id"]]
    read = authenticated_app_client.get(f"/api/v1/meetings/{meeting['id']}")
    assert read.json()["url"] == MEET


def test_a_link_it_cannot_join_is_refused_and_nothing_starts(
    authenticated_app_client: TestClient, started: list[int]
) -> None:
    response = authenticated_app_client.post(
        "/api/v1/meetings", json={"url": "https://example.com/x"}
    )

    assert response.status_code == 422
    assert "Google Meet" in response.json()["detail"]
    assert started == []


def test_the_bot_can_be_asked_to_leave(
    authenticated_app_client: TestClient, started: list[int]
) -> None:
    meeting = authenticated_app_client.post("/api/v1/meetings", json={"url": MEET})
    meeting_id = meeting.json()["id"]

    response = authenticated_app_client.post(f"/api/v1/meetings/{meeting_id}/leave")

    assert response.status_code == 202
    assert response.json()["status"] == "leaving"


def test_an_unknown_meeting_is_not_found(
    authenticated_app_client: TestClient,
) -> None:
    assert authenticated_app_client.get("/api/v1/meetings/999").status_code == 404


@pytest.fixture
def admin(authenticated_client: TestClient) -> TestClient:
    """Overseer's admin, reading and changing every owner's meetings."""
    return as_admin(authenticated_client)


async def _theirs(session: AsyncSession) -> tuple[int, list[int]]:
    """Another owner's meeting the bot has left: Ada said hi, for 42s."""
    meeting_id, lines = await ended(
        session, 4242, ("Ada", "Hi."), notes=lambda _: Notes(summary="Ada said hi.")
    )
    await save_heard(session, meeting_id, {"Ada": 42.0})
    return meeting_id, lines


async def test_the_admin_reads_every_owners_meetings(
    authenticated_client: TestClient, async_db_session: AsyncSession
) -> None:
    """Whoever Overseer lets in reads them: an admin, verified or not."""
    meeting_id, _ = await _theirs(async_db_session)

    response = authenticated_client.get(ADMIN)

    assert response.status_code == 200, response.text
    assert meeting_id in [m["id"] for m in response.json()]


async def test_one_meeting_comes_with_its_notes_transcript_and_what_was_heard(
    authenticated_client: TestClient, async_db_session: AsyncSession
) -> None:
    meeting_id, lines = await _theirs(async_db_session)

    body = authenticated_client.get(f"{ADMIN}/{meeting_id}").json()

    assert body["meeting"]["heard"] == {"Ada": 42.0}
    assert body["notes"]["summary"] == "Ada said hi."
    assert body["transcript"] == [
        {"id": lines[0], "speaker": "Ada", "at": 0.0, "text": "Hi."}
    ]


async def test_the_admin_deletes_a_meeting_but_not_one_the_bot_is_in(
    admin: TestClient, async_db_session: AsyncSession
) -> None:
    done, _ = await _theirs(async_db_session)
    live = await MeetingsService(async_db_session, 4242).request(MEET)
    live_id: int = live.id  # type: ignore[assignment]
    await transition(
        async_db_session,
        live_id,
        MeetingStatus.IN_CALL,
        from_=(MeetingStatus.REQUESTED,),
    )

    assert admin.delete(f"{ADMIN}/{done}").status_code == 204
    assert admin.get(f"{ADMIN}/{done}").status_code == 404
    assert admin.delete(f"{ADMIN}/{live_id}").status_code == 409
    left = admin.post(f"{ADMIN}/{live_id}/leave")
    assert left.json()["status"] == "leaving"


async def test_the_admin_says_who_the_owner_is_and_rewrites_the_notes(
    admin: TestClient, async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the Flet Overseer does from its pane, as the htmx drawer does."""
    _, runs = hold_the_writer(monkeypatch)
    meeting_id = await docs_meeting(async_db_session, 4242)

    picked = admin.post(f"{ADMIN}/{meeting_id}/me", json={"name": "Ada"})
    assert [item["text"] for item in picked.json()["mine"]] == ["Write the docs"]
    rewritten = admin.post(f"{ADMIN}/{meeting_id}/notes")
    assert rewritten.status_code == 202 and rewritten.json()["writing"]
    assert admin.post(f"{ADMIN}/{meeting_id}/notes").status_code == 409
    await runs[0]
