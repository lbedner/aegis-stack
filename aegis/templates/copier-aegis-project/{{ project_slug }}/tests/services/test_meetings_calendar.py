"""An agent's calendar, read from Google's secret iCal feed
(``domains.calendar``): each meeting on it, one per time it happens, with
the link the agent joins by; and the agent sent into each as it starts."""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.services.meetings.domains.accounts import service as accounts
from app.services.meetings.domains.calendar.entries import (
    CANCELLED,
    CANNOT_JOIN,
    MISSED,
    NO_LINK,
    UPCOMING,
    entries_between,
    month_days,
)
from app.services.meetings.domains.calendar.feed import meetings_between
from app.services.meetings.domains.calendar.service import read_calendars, send_due
from app.services.meetings.login import CALENDAR
from app.services.meetings.models import CalendarEvent, Meeting, MeetingStatus
from app.services.meetings.service import MeetingsService, transition
from tests._meetings import MEET, STANDUP, Calendar, at, feed, hold_the_bot

NOW = at(18, 0)
WEEK = (NOW, at(25, 0))
MONDAY, SUNDAY = date(2026, 10, 19), date(2026, 10, 25)

MOVED = f"""
UID:standup@google.com
RECURRENCE-ID;TZID=America/New_York:20261020T090000
DTSTART;TZID=America/New_York:20261020T100000
DTEND;TZID=America/New_York:20261020T101500
SUMMARY:Standup
X-GOOGLE-CONFERENCE:{MEET}
STATUS:CANCELLED
"""
LUNCH = "UID:lunch@example.com\nDTSTART:20261022T170000Z\nDTEND:20261022T180000Z"
VENDOR = """
UID:zoom@example.com
DTSTART:20261023T150000Z
DTEND:20261023T160000Z
SUMMARY:Vendor call
LOCATION:Room 4
DESCRIPTION:Agenda: https://example.com/doc\\nJoin: https://acme.zoom.us/j/123
"""


def test_a_recurring_meeting_is_one_meeting_each_time_it_happens() -> None:
    """Each time is its own, in UTC, kept apart by when it was first set
    for: a time moved or cancelled on its own is still the same one."""
    standups = meetings_between(feed(STANDUP, MOVED), *WEEK)

    assert [m.starts_at.hour for m in standups] == [13, 14, 13]
    assert len({m.key for m in standups}) == 3
    moved = standups[1]
    assert moved.cancelled and not standups[0].cancelled
    assert moved.key.endswith("20261020T130000Z")
    assert standups[0].url == MEET
    assert standups[0].title == "Standup"
    assert standups[0].organizer == "Dana"
    assert standups[0].emails == ["dana@example.com", "leo@example.com"]


def test_the_link_is_found_where_the_invite_put_it() -> None:
    """The conference Google attached, else the first meeting link in the
    location or description; a meeting with none has none, and a day-long
    event is not a meeting."""
    holiday = """
UID:holiday@example.com
DTSTART;VALUE=DATE:20261024
DTEND;VALUE=DATE:20261025
SUMMARY:Holiday
"""
    found = meetings_between(feed(VENDOR, LUNCH, holiday), *WEEK)

    assert [(m.title, m.url) for m in found] == [
        ("", None),
        ("Vendor call", "https://acme.zoom.us/j/123"),
    ]


async def kept(db: AsyncSession) -> list[CalendarEvent]:
    query = select(CalendarEvent).order_by(col(CalendarEvent.starts_at))
    return list((await db.exec(query)).all())


@pytest.mark.queryspy(allow_n_plus_one=True)  # read, then read again
async def test_each_read_keeps_the_calendar_as_it_is_now(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A meeting moved is moved and one taken off is gone, unless the agent
    was already sent into it: what happened stays. One not sent is dropped
    once it is more than a month behind."""
    hold_the_bot(monkeypatch)
    calendar = Calendar(monkeypatch, STANDUP)

    assert await read_calendars(async_db_session, calendar.read, NOW) == {
        accounts.DEFAULT_AGENT: 3
    }
    [sent] = await send_due(async_db_session, at(19, 13))
    calendar.shows(
        STANDUP.replace("COUNT=3", "COUNT=1").replace("20261019T09", "20261020T09"),
        MOVED,
    )
    await read_calendars(async_db_session, calendar.read, NOW)

    rows = await kept(async_db_session)
    assert [(r.starts_at.day, r.starts_at.hour, r.cancelled) for r in rows] == [
        (19, 13, False),
        (20, 14, True),
    ]
    assert rows[0].meeting_id == sent

    calendar.shows()
    await read_calendars(async_db_session, calendar.read, NOW + timedelta(days=60))
    assert [r.meeting_id for r in await kept(async_db_session)] == [sent]


async def test_another_agent_has_its_own_calendar(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kept under ``CALENDAR__<NAME>``. An agent with none is skipped, and
    one whose calendar cannot be read keeps what it had."""
    calendar = Calendar(monkeypatch, STANDUP, secret=f"{CALENDAR}__WORK")
    work = await accounts.keep_agent(async_db_session, "work", "Work", None)

    assert await read_calendars(async_db_session, calendar.read, NOW) == {"work": 3}
    calendar.ics = ConnectionError("down")
    assert await read_calendars(async_db_session, calendar.read, NOW) == {}

    rows = await kept(async_db_session)
    assert [r.account_id for r in rows] == [work.id] * 3


@pytest.mark.queryspy(allow_n_plus_one=True)  # one send after another
async def test_the_agent_is_sent_into_each_meeting_as_it_starts(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once, as the agent whose calendar it is on, up to a minute early,
    even if that meeting is then deleted; never into one cancelled, one with
    no link, one on a platform the bot does not join yet, or one already
    over. A meeting with nobody on it who has an account here is nobody's."""
    started = hold_the_bot(monkeypatch)
    calendar = Calendar(monkeypatch, STANDUP, MOVED, LUNCH, VENDOR)
    await read_calendars(async_db_session, calendar.read, NOW)

    assert await send_due(async_db_session, at(19, 12, 58)) == []
    [sent] = await send_due(async_db_session, at(19, 12, 59, 30))
    meeting = await async_db_session.get(Meeting, sent)
    [first] = await accounts.agents(async_db_session)
    assert meeting is not None
    assert (meeting.url, meeting.account_id) == (MEET, first.id)
    assert meeting.bot_name == first.display_name
    assert meeting.owner_user_id is None

    await transition(
        async_db_session, sent, MeetingStatus.FAILED, from_=(MeetingStatus.REQUESTED,)
    )
    await MeetingsService(async_db_session, None).delete(sent)
    assert await send_due(async_db_session, at(19, 13, 5)) == []
    assert await send_due(async_db_session, at(20, 14)) == []
    assert await send_due(async_db_session, at(21, 13, 20)) == []
    assert await send_due(async_db_session, at(22, 17)) == []
    assert await send_due(async_db_session, at(23, 15)) == []
    assert started == [sent]


def test_a_month_is_whole_weeks_monday_to_sunday() -> None:
    assert month_days(date(2026, 10, 18)) == (date(2026, 9, 28), date(2026, 11, 1))
    assert month_days(date(2026, 2, 1)) == (date(2026, 1, 26), date(2026, 3, 1))


async def test_no_agent_is_sent_while_joining_from_calendars_is_off(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``MEETINGS_JOIN_FROM_CALENDAR`` off: the calendar is still kept and
    shown, and nobody is sent into it."""
    started = hold_the_bot(monkeypatch)
    monkeypatch.setattr(settings, "MEETINGS_JOIN_FROM_CALENDAR", False)
    calendar = Calendar(monkeypatch, STANDUP)
    await read_calendars(async_db_session, calendar.read, NOW)

    assert await send_due(async_db_session, at(19, 13)) == []
    assert started == []
    assert len(await kept(async_db_session)) == 3


@pytest.mark.queryspy(allow_n_plus_one=True)  # a send, then the reads
async def test_every_agents_calendar_between_two_days(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whole days in the viewer's time zone, each meeting with its agent
    and its color, and where it stands: the call it became, missed,
    upcoming, cancelled, with no link, or one the bot cannot join yet. One
    agent's alone, or only the invites one email is on."""
    hold_the_bot(monkeypatch)
    calendar = Calendar(monkeypatch, STANDUP, MOVED, LUNCH, VENDOR)
    await read_calendars(async_db_session, calendar.read, NOW)
    [sent] = await send_due(async_db_session, at(19, 13))
    new_york = ZoneInfo("America/New_York")

    week = await entries_between(
        async_db_session, MONDAY, SUNDAY, new_york, now=at(21, 14)
    )

    assert [(e.starts_at.day, e.starts_at.hour, e.state) for e in week] == [
        (19, 9, "Requested"),
        (20, 10, CANCELLED),
        (21, 9, MISSED),
        (22, 13, NO_LINK),
        (23, 11, CANNOT_JOIN),
    ]
    assert week[0].meeting_id == sent
    assert {e.agent for e in week} == {accounts.DEFAULT_AGENT}
    assert week[0].color == week[4].color
    assert week[0].starts_at.tzinfo == new_york
    later = await entries_between(
        async_db_session, MONDAY, SUNDAY, new_york, now=at(19, 0)
    )
    assert later[2].state == UPCOMING
    one_day = await entries_between(async_db_session, SUNDAY, SUNDAY, new_york)
    assert one_day == []
    assert (
        await entries_between(async_db_session, MONDAY, SUNDAY, new_york, "work") == []
    )
    invited = await entries_between(
        async_db_session, MONDAY, SUNDAY, new_york, email="leo@example.com"
    )
    assert [e.title for e in invited] == ["Standup"] * 2
    nobody = await entries_between(
        async_db_session, MONDAY, SUNDAY, new_york, email="nobody@example.com"
    )
    assert nobody == []
