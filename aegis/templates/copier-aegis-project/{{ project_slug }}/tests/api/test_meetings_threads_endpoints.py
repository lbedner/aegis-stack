"""A meeting's commitments, contradictions and positions over HTTP, each
with the lines it cites: the owner's own, and every owner's for
Overseer's admin. A person's come with their guide (``GuideRecord``)."""

from typing import Any

from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.models import Commitment, Notes
from tests._meetings import ended, someone_else

MEETINGS = "/api/v1/meetings"
ADMIN = "/api/v1/meetings/admin"


async def _promised(session: AsyncSession, owner: int | None) -> int:
    meeting_id, _ = await ended(
        session,
        owner,
        ("Ada", "I'll send the deck."),
        notes=lambda ids: Notes(
            summary="-",
            commitments=[Commitment(text="Send the deck", owner="Ada", lines=ids)],
        ),
    )
    return meeting_id


def _commitments(response: Any) -> list[dict[str, Any]]:
    assert response.status_code == 200, response.text
    return next(s for s in response.json() if s["key"] == "commitments")["items"]


async def test_an_owner_reads_a_meetings_threads(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    meeting_id = await _promised(async_db_session, acting_owner_user_id)

    (deck,) = _commitments(authenticated_client.get(f"{MEETINGS}/{meeting_id}/threads"))

    assert deck["text"] == "Send the deck"
    assert deck["quotes"][0]["text"] == "I'll send the deck."


async def test_another_owners_meeting_is_not_found(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    if acting_owner_user_id is None:
        pytest.skip("Without auth every meeting is the one owner's")
    theirs = await _promised(async_db_session, await someone_else(async_db_session))

    assert authenticated_client.get(f"{MEETINGS}/{theirs}/threads").status_code == 404


async def test_the_admin_reads_every_owners(
    authenticated_client: TestClient, async_db_session: AsyncSession
) -> None:
    theirs = await _promised(async_db_session, await someone_else(async_db_session))

    (deck,) = _commitments(authenticated_client.get(f"{ADMIN}/{theirs}/threads"))

    assert deck["speaker"] == "Ada"
