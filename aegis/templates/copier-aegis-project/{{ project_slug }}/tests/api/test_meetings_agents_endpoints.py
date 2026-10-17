"""The meeting agents over HTTP: the bot sent as one by name, and every
agent listed for Overseer with whether its sign-in works and where it is."""

from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.accounts.service import (
    DEFAULT_AGENT,
    NOT_SIGNED_IN,
    keep_agent,
)
from tests._meetings import MEET, hold_the_bot
from tests._secret_settings import use_store

AGENTS = "/api/v1/meetings/admin/agents"


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
    use_store(monkeypatch)
    await keep_agent(async_db_session, "work", "Work Notes", "notes@work.example")

    response = authenticated_client.get(AGENTS)

    assert response.status_code == 200, response.text
    rows = {row["account"]["name"]: row for row in response.json()}
    assert set(rows) == {DEFAULT_AGENT, "work"}
    assert rows["work"]["account"]["email"] == "notes@work.example"
    assert rows["work"]["sign_in"] == NOT_SIGNED_IN
    assert rows["work"]["in_now"] == []
