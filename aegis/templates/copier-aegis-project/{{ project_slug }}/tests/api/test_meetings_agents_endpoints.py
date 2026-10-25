"""The meeting agents over HTTP: the bot sent as one by name, every agent
listed for Overseer with whether its sign-in works and where it is, their
calendars, and each one's card (its picture, its camera)."""

from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.accounts.service import (
    DEFAULT_AGENT,
    NOT_SIGNED_IN,
    keep_agent,
)
from app.services.meetings.domains.calendar.service import read_calendars
from tests._audit import as_admin, let_into_overseer
from tests._meetings import MEET, PIXEL_PNG, STANDUP, Calendar, at, hold_the_bot
from tests._secret_settings import use_store

AGENTS = "/api/v1/meetings/admin/agents"
CALENDAR = "/api/v1/meetings/admin/calendar"


async def test_the_bot_is_sent_as_the_agent_named(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = hold_the_bot(monkeypatch)
    work = await keep_agent(async_db_session, "work", "Work Notes", None)

    sent = authenticated_client.post(
        "/api/v1/meetings", json={"url": MEET, "agent": "work"}
    )
    unknown = authenticated_client.post(
        "/api/v1/meetings", json={"url": MEET, "agent": "nobody"}
    )

    assert sent.status_code == 202, sent.text
    assert sent.json()["account_id"] == work.id
    assert sent.json()["bot_name"] == "Work Notes"
    assert unknown.status_code == 422 and "nobody" in unknown.json()["detail"]
    assert started == [sent.json()["id"]]


async def test_overseer_lists_every_agent(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    let_into_overseer(authenticated_client, monkeypatch)
    use_store(monkeypatch)
    await keep_agent(async_db_session, "work", "Work Notes", "notes@work.example")

    response = authenticated_client.get(AGENTS)

    assert response.status_code == 200, response.text
    rows = {row["account"]["name"]: row for row in response.json()}
    assert set(rows) == {DEFAULT_AGENT, "work"}
    assert rows["work"]["account"]["email"] == "notes@work.example"
    assert rows["work"]["sign_in"] == NOT_SIGNED_IN
    assert rows["work"]["in_now"] == []


async def test_overseer_reads_every_agents_calendar(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In the time zone asked for; one it does not know is refused, and so
    is more than six weeks."""
    let_into_overseer(authenticated_client, monkeypatch)
    calendar = Calendar(monkeypatch, STANDUP)
    await read_calendars(async_db_session, calendar.read, at(18, 0))

    days = {"first": "2026-10-19", "last": "2026-10-21"}
    week = authenticated_client.get(CALENDAR, params=days | {"tz": "America/New_York"})
    unknown = authenticated_client.get(CALENDAR, params=days | {"tz": "Mars/Olympus"})
    too_long = authenticated_client.get(
        CALENDAR, params={"first": "2026-10-01", "last": "2026-12-01"}
    )

    assert week.status_code == 200, week.text
    assert [e["starts_at"][:16] for e in week.json()] == [
        "2026-10-19T09:00",
        "2026-10-20T09:00",
        "2026-10-21T09:00",
    ]
    assert {e["agent"] for e in week.json()} == {DEFAULT_AGENT}
    assert unknown.status_code == 422 and "Mars/Olympus" in unknown.json()["detail"]
    assert too_long.status_code == 422


async def test_overseer_opens_one_meeting_on_a_calendar(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With who is invited; an id on no calendar is a 404."""
    let_into_overseer(authenticated_client, monkeypatch)
    await read_calendars(
        async_db_session, Calendar(monkeypatch, STANDUP).read, at(18, 0)
    )
    days = {"first": "2026-10-19", "last": "2026-10-19"}
    [standup] = authenticated_client.get(CALENDAR, params=days).json()

    opened = authenticated_client.get(f"{CALENDAR}/{standup['id']}")
    missing = authenticated_client.get(f"{CALENDAR}/0")

    assert opened.status_code == 200, opened.text
    assert [i["email"] for i in opened.json()["invited"]] == [
        "dana@example.com",
        "leo@example.com",
    ]
    assert missing.status_code == 404


async def test_overseer_sets_an_agents_picture_and_camera(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = as_admin(let_into_overseer(authenticated_client, monkeypatch))
    use_store(monkeypatch)
    image = f"{AGENTS}/{DEFAULT_AGENT}/image"

    put = client.post(image, files={"file": ("me.png", PIXEL_PNG, "image/png")})
    shown = client.get(image)
    listed = client.get(AGENTS).json()
    camera = client.put(f"{AGENTS}/{DEFAULT_AGENT}/camera", json={"on": False})
    owner_only = client.put(
        f"{AGENTS}/{DEFAULT_AGENT}/answers_anyone", json={"on": False}
    )
    unknown = client.put(f"{AGENTS}/{DEFAULT_AGENT}/sings", json={"on": True})
    refused = client.post(image, files={"file": ("a.pdf", b"%PDF", "application/pdf")})
    gone = client.delete(image)

    assert put.status_code == 200, put.text
    assert shown.content == PIXEL_PNG and shown.headers["content-type"] == "image/png"
    assert listed[0]["image"] is not None
    assert camera.json()["camera"] is False
    assert owner_only.json()["answers_anyone"] is False
    assert unknown.status_code in (404, 405, 422)
    assert refused.status_code == 422
    assert gone.status_code == 204
    assert client.get(image).status_code == 404
