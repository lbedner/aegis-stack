"""How to work with each person, over HTTP: an owner's guides, one read
with the lines each point rests on, the owner's note on it, and the guide
written again; and every owner's, for Overseer's admin."""

from typing import Any

from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.people import service as people_service
from app.services.meetings.models import NoteItem, Notes
from tests._audit import as_admin, let_into_overseer
from tests._meetings import ended, kept_guide, someone_else

PEOPLE = "/api/v1/meetings/people"
ADMIN = "/api/v1/meetings/admin/people"


async def test_an_owner_reads_their_guides_with_the_lines_they_rest_on(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    _, ids = await ended(
        async_db_session,
        acting_owner_user_id,
        ("Ada", "Numbers first."),
        notes=lambda _: Notes(summary="-"),
    )
    guide_id = await kept_guide(
        async_db_session,
        acting_owner_user_id,
        "Ada",
        information=[NoteItem(text="The numbers first", lines=ids)],
    )

    listed = authenticated_client.get(PEOPLE)
    read = authenticated_client.get(f"{PEOPLE}/{guide_id}")

    assert listed.status_code == 200, listed.text
    assert [g["person"] for g in listed.json()] == ["Ada"]
    information = next(s for s in read.json()["sections"] if s["key"] == "information")
    assert information["points"][0]["quotes"][0]["text"] == "Numbers first."


async def test_another_owners_guide_is_not_found(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    if acting_owner_user_id is None:
        pytest.skip("Without auth every guide is the one owner's")
    theirs = await kept_guide(
        async_db_session, await someone_else(async_db_session), "Ada"
    )

    assert authenticated_client.get(f"{PEOPLE}/{theirs}").status_code == 404


async def test_the_owners_note_is_kept_and_the_guide_written_again(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guide_id = await kept_guide(async_db_session, acting_owner_user_id, "Ada")
    monkeypatch.setattr(people_service, "guide_writer", lambda: None)

    noted = authenticated_client.put(
        f"{PEOPLE}/{guide_id}/note", json={"note": "Calls, not email."}
    )
    refused = authenticated_client.post(f"{PEOPLE}/{guide_id}/guide")

    assert noted.json()["guide"]["note"] == "Calls, not email."
    assert refused.status_code == 409
    runs: list[Any] = []

    async def write(person_id: int) -> None:
        return None

    monkeypatch.setattr(people_service, "guide_writer", lambda: write)
    monkeypatch.setattr(people_service, "background", runs.append)
    monkeypatch.setattr(people_service, "GUIDING", set())
    started = authenticated_client.post(f"{PEOPLE}/{guide_id}/guide")
    assert started.status_code == 202 and started.json()["writing"]
    for run in runs:
        await run


async def test_the_admin_reads_every_owners_guides(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    let_into_overseer(authenticated_client, monkeypatch)
    theirs = await kept_guide(
        async_db_session, await someone_else(async_db_session), "Ada"
    )

    listed = authenticated_client.get(ADMIN)
    read = authenticated_client.get(f"{ADMIN}/{theirs}")

    assert listed.status_code == 200, listed.text
    assert theirs in [g["guide"]["id"] for g in listed.json()]
    assert read.json()["person"] == "Ada"


async def test_the_admin_writes_one_again(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = as_admin(authenticated_client)
    theirs = await kept_guide(
        async_db_session, await someone_else(async_db_session), "Ada"
    )
    monkeypatch.setattr(people_service, "guide_writer", lambda: None)

    assert admin.post(f"{ADMIN}/{theirs}/guide").status_code == 409
    noted = admin.put(f"{ADMIN}/{theirs}/note", json={"note": "Short answers."})
    assert noted.json()["guide"]["note"] == "Short answers."
