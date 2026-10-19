"""Overseer > Meetings > Series: what each series of meetings keeps coming
back to, every owner's for the admin. A row opens one series in the
drawer, its summary over time and each theme with the lines it was said
in; it is written again from there."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.web_frontend import overseer_meetings
from app.services.meetings.domains.series import service as series_service
from app.services.meetings.models import NoteItem, Theme
from app.services.system.models import ComponentStatus
from tests._meetings import asked_twice, hold_the_series_writer, kept_series
from tests.web.dom import none, one, select, text
from tests.web.overseer import page_html, sign_in, status_with

SERIES = f"{overseer_meetings.PAGE}/series"
PARTIALS = f"{overseer_meetings.PARTIALS}/series"
MEETINGS = ComponentStatus(name="meetings", message="Meetings ready")
HX = {"HX-Request": "true"}


@pytest.fixture
def overseer(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, async_client_with_db: TestClient
) -> TestClient:
    """Signed in as an admin, on the test's own session."""
    sign_in(app, monkeypatch, status_with(services=[MEETINGS]))
    return async_client_with_db


async def _series(session: AsyncSession) -> tuple[int, list[int]]:
    """Owner 4242's series, where Dana asked for the report twice: its id
    and the meetings."""
    meetings, asked = await asked_twice(session, 4242)
    series_id = await kept_series(
        session,
        4242,
        name="Dev call",
        summary="Dana keeps asking for the report.",
        themes=[Theme(text="The usage report", lines=asked)],
        still_open=[NoteItem(text="The usage report", lines=asked)],
    )
    return series_id, meetings


async def test_every_owners_series_are_listed(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    series_id, _ = await _series(async_db_session)

    (row,) = select(page_html(overseer, SERIES), "#overseer-meeting-series tbody tr")

    link = one(row, "a")
    assert text(link) == "Dev call"
    assert f"series={series_id}" in (link.get("href") or "")


async def test_a_series_opens_with_each_theme_and_its_lines(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    series_id, meetings = await _series(async_db_session)

    page = page_html(overseer, f"{SERIES}?series={series_id}")
    sync = one(page, "[data-drawer-sync]")
    assert sync.get("data-drawer-url") == f"{PARTIALS}/{series_id}/drawer"
    html = page_html(overseer, f"{PARTIALS}/{series_id}/drawer")

    facts = {text(dt): text(dt.getnext()) for dt in select(html, "dl dt")}
    assert facts["Owner"] == "4242" and facts["Read from"] == "2 meetings"
    tabs = one(html, "[data-tabs]")
    assert [text(t) for t in select(tabs, "[role=tab]")] == [
        "Over time",
        "Keeps coming up",
    ]
    assert "Dana keeps asking for the report." in text(one(html, "[data-summary]"))
    still_open = one(html, '[data-card="still_open"]')
    assert "The usage report" in text(still_open)
    assert f"Since meeting {meetings[0]}" in text(still_open)
    none(html, '[data-card="settled"]')
    theme = one(html, '[data-thread-section="themes"] [data-thread]')
    assert "The usage report" in text(theme) and "2 meetings" in text(theme)
    links = [one(q, "a").get("href") or "" for q in select(theme, "[data-quote]")]
    assert [f"meeting={m}" in link for link, m in zip(links, meetings)] == [True] * 2


async def test_a_series_is_written_again_from_the_drawer(
    overseer: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs = hold_the_series_writer(monkeypatch)
    series_id, _ = await _series(async_db_session)
    one(page_html(overseer, f"{PARTIALS}/{series_id}/drawer"), "[data-write-series]")

    response = overseer.post(f"{PARTIALS}/{series_id}/write", headers=HX)

    assert response.status_code == 200, response.text
    assert one(response.text, "#series-body").get("hx-trigger") == "every 3s"
    none(response.text, "[data-write-series]")
    for run in runs:
        await run


async def test_without_a_model_there_is_nothing_to_write_with(
    overseer: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(series_service, "themes_writer", lambda: None)
    series_id, _ = await _series(async_db_session)

    none(page_html(overseer, f"{PARTIALS}/{series_id}/drawer"), "[data-write-series]")
    assert overseer.post(f"{PARTIALS}/{series_id}/write", headers=HX).status_code == 409
