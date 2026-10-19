"""What each series of meetings keeps coming back to, over HTTP: an
owner's series, one read with each theme's lines, and one written again;
and every owner's, for Overseer's admin."""

from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.series import service as series_service
from app.services.meetings.models import Theme
from tests._audit import as_admin
from tests._meetings import (
    asked_twice,
    hold_the_series_writer,
    kept_series,
    someone_else,
)

SERIES = "/api/v1/meetings/series"
ADMIN = "/api/v1/meetings/admin/series"


async def _series(session: AsyncSession, owner: int | None) -> int:
    """The owner's series, where Dana asked for the report twice."""
    _, asked = await asked_twice(session, owner)
    return await kept_series(
        session, owner, themes=[Theme(text="The usage report", lines=asked)]
    )


async def test_an_owner_reads_their_series_with_each_themes_lines(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    series_id = await _series(async_db_session, acting_owner_user_id)

    listed = authenticated_client.get(SERIES)
    read = authenticated_client.get(f"{SERIES}/{series_id}")

    assert listed.status_code == 200, listed.text
    assert [s["series"]["id"] for s in listed.json()] == [series_id]
    (theme,) = read.json()["sections"][0]["items"]
    assert [q["text"] for q in theme["quotes"]] == [
        "The usage report?",
        "Still no report.",
    ]


async def test_another_owners_series_is_not_found(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    if acting_owner_user_id is None:
        pytest.skip("Without auth every series is the one owner's")
    theirs = await kept_series(async_db_session, await someone_else(async_db_session))

    assert authenticated_client.get(f"{SERIES}/{theirs}").status_code == 404


async def test_a_series_is_written_again(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series_id = await _series(async_db_session, acting_owner_user_id)
    monkeypatch.setattr(series_service, "themes_writer", lambda: None)
    assert authenticated_client.post(f"{SERIES}/{series_id}/write").status_code == 409
    runs = hold_the_series_writer(monkeypatch)

    started = authenticated_client.post(f"{SERIES}/{series_id}/write")

    assert started.status_code == 202 and started.json()["writing"]
    for run in runs:
        await run


async def test_the_admin_reads_and_writes_every_owners_series(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = as_admin(authenticated_client)
    theirs = await _series(async_db_session, await someone_else(async_db_session))
    runs = hold_the_series_writer(monkeypatch)

    assert theirs in [s["series"]["id"] for s in admin.get(ADMIN).json()]
    assert admin.get(f"{ADMIN}/{theirs}").json()["series"]["id"] == theirs
    assert admin.post(f"{ADMIN}/{theirs}/write").status_code == 202
    for run in runs:
        await run
