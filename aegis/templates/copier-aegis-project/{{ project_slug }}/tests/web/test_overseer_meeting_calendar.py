"""Overseer > Meetings > Calendar: a month of every agent's calendar, in
the viewer's time zone, each agent in its own color, filtered to one agent,
each meeting the agent was sent into opening in the Meetings drawer."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.web_frontend import overseer_meetings
from app.components.web_frontend.rendering import TZ_COOKIE
from app.services.meetings.domains.accounts.service import DEFAULT_AGENT, keep_agent
from app.services.meetings.domains.calendar.service import read_calendars, send_due
from app.services.system.models import ComponentStatus
from tests._meetings import MEET, STANDUP, Calendar, at, hold_the_bot
from tests.web.dom import one, select, text
from tests.web.overseer import page_html, sign_in, status_with

CALENDAR = f"{overseer_meetings.PAGE}/calendar"
MEETINGS = ComponentStatus(name="meetings", message="Meetings ready")
LUNCH = "UID:lunch@example.com\nDTSTART:20261022T170000Z\nDTEND:20261022T180000Z\nSUMMARY:Lunch"


@pytest.fixture
def overseer(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, async_client_with_db: TestClient
) -> TestClient:
    """Signed in as an admin, on the test's own session."""
    sign_in(app, monkeypatch, status_with(services=[MEETINGS]))
    return async_client_with_db


@pytest.mark.queryspy(allow_n_plus_one=True)  # the calendar read, then a send
async def test_a_month_of_every_agents_meetings_in_the_viewers_time(
    overseer: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hold_the_bot(monkeypatch)
    calendar = Calendar(monkeypatch, STANDUP, LUNCH)
    await read_calendars(async_db_session, calendar.read, at(18, 0))
    [sent] = await send_due(async_db_session, at(19, 13))
    await keep_agent(async_db_session, "work", "Work Notes", None)
    overseer.cookies.set(TZ_COOKIE, "America/New_York")

    html = page_html(overseer, f"{CALENDAR}?month=2026-10")

    days = select(html, "#overseer-meeting-calendar [data-day]")
    assert (days[0].get("data-day"), days[-1].get("data-day")) == (
        "2026-09-28",
        "2026-11-01",
    )
    assert len(days) == 35
    outside = [d.get("data-day") for d in days if d.get("data-outside") is not None]
    assert outside == ["2026-09-28", "2026-09-29", "2026-09-30", "2026-11-01"]
    assert "October 2026" in text(select(html, "#overseer-meeting-calendar h2")[0])
    monday = select(html, '[data-day="2026-10-19"] [data-entry]')
    assert len(monday) == 1
    assert "09:00" in text(monday[0]) and "Standup" in text(monday[0])
    assert "Requested" in (monday[0].get("title") or "")
    [details] = select(html, '[data-day="2026-10-19"] [data-entry] a[data-details]')
    assert "month=2026-10" in (details.get("href") or "")
    assert "13:00" in text(select(html, '[data-day="2026-10-22"] [data-entry]')[0])
    agents = [text(a) for a in select(html, "[data-agent-filter] a")]
    assert agents == ["All agents", DEFAULT_AGENT, "work"]
    [earlier] = select(html, "a[data-month-earlier]")
    assert "month=2026-09" in (earlier.get("href") or "")
    [later] = select(html, "a[data-month-later]")
    assert "month=2026-11" in (later.get("href") or "")


@pytest.mark.queryspy(allow_n_plus_one=True)  # the calendar read, then a send
async def test_a_meeting_on_it_opens_with_what_its_invite_says(
    overseer: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any meeting on the calendar opens in the drawer: when, whose calendar,
    where it stands, who organized it and who is invited, its link, and the
    call the agent was sent into, when it was."""
    hold_the_bot(monkeypatch)
    calendar = Calendar(monkeypatch, STANDUP)
    await read_calendars(async_db_session, calendar.read, at(18, 0))
    [sent] = await send_due(async_db_session, at(19, 13))

    html = page_html(overseer, f"{CALENDAR}?month=2026-10")
    [details] = select(html, '[data-day="2026-10-19"] [data-entry] a[data-details]')
    opened = page_html(overseer, details.get("href") or "")
    drawer_url = one(opened, "[data-drawer-sync]").get("data-drawer-url") or ""
    drawer = page_html(overseer, drawer_url)

    assert "Standup" in text(one(drawer, "h2"))
    facts = [text(d) for d in select(drawer, "dd")]
    assert DEFAULT_AGENT in facts and "Dana" in facts
    invited = [text(li) for li in select(drawer, "[data-invited] li")]
    assert invited == ["dana@example.com", "leo@example.com"]
    assert one(drawer, "a[data-link]").get("href") == MEET
    assert one(drawer, "a[data-opens]").get("href") == overseer_meetings.meeting_url(
        sent
    )


@pytest.mark.queryspy(allow_n_plus_one=True)  # two renders
async def test_one_agents_calendar_and_utc_without_a_time_zone(
    overseer: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar = Calendar(monkeypatch, STANDUP)
    await read_calendars(async_db_session, calendar.read, at(18, 0))
    await keep_agent(async_db_session, "work", "Work Notes", None)

    every = page_html(overseer, f"{CALENDAR}?month=2026-10")
    work = page_html(overseer, f"{CALENDAR}?month=2026-10&agent=work")

    [monday] = select(every, '[data-day="2026-10-19"] [data-entry]')
    assert "13:00" in text(monday)
    assert select(work, "[data-entry]") == []


def test_the_meetings_page_has_its_own_settings(overseer: TestClient) -> None:
    """Its section lists what meetings can be configured with, joining
    from the agents' calendars among them."""
    html = page_html(overseer, f"{overseer_meetings.PAGE}/settings")

    assert "MEETINGS_JOIN_FROM_CALENDAR" in html
    assert "MEETINGS_KEEP_AUDIO_DIR" in html
