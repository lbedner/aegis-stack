"""Search over HTTP: the caller's own meetings, and every owner's for
Overseer's admin."""

from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.models import Notes
from tests._audit import let_into_overseer
from tests._meetings import ended, someone_else

SEARCH = "/api/v1/meetings/search"
ADMIN = "/api/v1/meetings/admin/search"


async def test_a_word_said_finds_its_line(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    meeting_id, ids = await ended(
        async_db_session,
        acting_owner_user_id,
        ("Lawrence", "Our pricing is too low."),
        notes=lambda _: Notes(summary="-"),
    )

    found = authenticated_client.get(SEARCH, params={"q": "pricing"})

    assert found.status_code == 200, found.text
    (hit,) = found.json()
    assert (hit["meeting_id"], hit["speaker"], hit["line_id"], hit["text"]) == (
        meeting_id,
        "Lawrence",
        ids[0],
        "Our pricing is too low.",
    )


async def test_another_owners_meetings_are_not_searched(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    if acting_owner_user_id is None:
        pytest.skip("Without auth every meeting is the one owner's")
    await ended(
        async_db_session,
        await someone_else(async_db_session),
        ("Grace", "Pricing."),
        notes=lambda _: Notes(summary="-"),
    )

    assert authenticated_client.get(SEARCH, params={"q": "pricing"}).json() == []


async def test_the_admin_searches_every_owners_meetings(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    let_into_overseer(authenticated_client, monkeypatch)
    theirs, _ = await ended(
        async_db_session,
        await someone_else(async_db_session),
        ("Grace", "Pricing."),
        notes=lambda _: Notes(summary="-"),
    )

    found = authenticated_client.get(ADMIN, params={"q": "pricing"})

    assert found.status_code == 200, found.text
    assert theirs in [hit["meeting_id"] for hit in found.json()]


def test_a_search_needs_words(authenticated_client: TestClient) -> None:
    assert authenticated_client.get(SEARCH).status_code == 422
