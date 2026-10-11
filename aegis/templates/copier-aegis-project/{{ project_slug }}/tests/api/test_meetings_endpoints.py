"""Meetings over HTTP: asking the bot into a call starts it in the
background and answers at once; the meeting is then read back, and the bot
asked to leave. Through ``authenticated_app_client`` so the suite runs with
and without the auth service."""

from fastapi.testclient import TestClient
import pytest

from app.components.backend.api.meetings import router as meetings_router

MEET = "https://meet.google.com/abc-defg-hij"


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The meetings the bot was started on, without starting it."""
    ids: list[int] = []
    monkeypatch.setattr(meetings_router, "start_meeting", ids.append)
    return ids


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
