"""An agent's calendar, read from Google's secret iCal feed
(``domains.calendar``): each meeting on it, one per time it happens, with
the link the agent joins by."""

from datetime import UTC, datetime

import pytest
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.accounts import service as accounts
from app.services.meetings.domains.calendar.feed import meetings_between
from app.services.meetings.domains.calendar.service import read_calendars
from app.services.meetings.login import CALENDAR
from app.services.meetings.models import CalendarEvent
from app.services.meetings.service import MeetingsService
from tests._meetings import MEET
from tests._secret_settings import use_store

NOW = datetime(2026, 10, 18, tzinfo=UTC)
WEEK = (NOW, datetime(2026, 10, 25, tzinfo=UTC))


def feed(*events: str) -> str:
    body = "".join(f"BEGIN:VEVENT\n{event.strip()}\nEND:VEVENT\n" for event in events)
    return f"BEGIN:VCALENDAR\nVERSION:2.0\n{body}END:VCALENDAR\n"


STANDUP = """
UID:standup@google.com
DTSTART;TZID=America/New_York:20261019T090000
DTEND;TZID=America/New_York:20261019T091500
RRULE:FREQ=DAILY;COUNT=3
SUMMARY:Standup
ORGANIZER;CN=Dana:mailto:dana@example.com
X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij
"""
MOVED = """
UID:standup@google.com
RECURRENCE-ID;TZID=America/New_York:20261020T090000
DTSTART;TZID=America/New_York:20261020T100000
DTEND;TZID=America/New_York:20261020T101500
SUMMARY:Standup
X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij
STATUS:CANCELLED
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
    assert standups[0].url == "https://meet.google.com/abc-defg-hij"
    assert standups[0].title == "Standup"
    assert standups[0].organizer == "Dana"


def test_the_link_is_found_where_the_invite_put_it() -> None:
    """The conference Google attached, else the first link the agent can
    join in the location or description; a meeting with none has none, and
    a day-long event is not a meeting."""
    zoom = """
UID:zoom@example.com
DTSTART:20261021T150000Z
DTEND:20261021T160000Z
SUMMARY:Vendor call
LOCATION:Room 4
DESCRIPTION:Agenda: https://example.com/doc\\nJoin: https://acme.zoom.us/j/123
"""
    lunch = """
UID:lunch@example.com
DTSTART:20261022T170000Z
DTEND:20261022T180000Z
SUMMARY:Lunch
"""
    holiday = """
UID:holiday@example.com
DTSTART;VALUE=DATE:20261023
DTEND;VALUE=DATE:20261024
SUMMARY:Holiday
"""
    found = meetings_between(feed(zoom, lunch, holiday), *WEEK)

    assert [(m.title, m.url) for m in found] == [
        ("Vendor call", "https://acme.zoom.us/j/123"),
        ("Lunch", None),
    ]


class Feeds:
    """Each calendar address and what reading it gives, or raises."""

    def __init__(self) -> None:
        self.by_url: dict[str, str | Exception] = {}

    async def read(self, url: str) -> str:
        found = self.by_url[url]
        if isinstance(found, Exception):
            raise found
        return found


async def kept(db: AsyncSession) -> list[CalendarEvent]:
    query = select(CalendarEvent).order_by(col(CalendarEvent.starts_at))
    return list((await db.exec(query)).all())


@pytest.mark.queryspy(allow_n_plus_one=True)  # read, then read again
async def test_each_read_keeps_the_calendar_as_it_is_now(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A meeting moved is moved and one taken off is gone, unless the agent
    was already sent into it: what happened stays."""
    use_store(monkeypatch).values[CALENDAR] = "https://calendar/first"
    feeds = Feeds()
    feeds.by_url["https://calendar/first"] = feed(STANDUP)

    assert await read_calendars(async_db_session, feeds.read, NOW) == {
        accounts.DEFAULT_AGENT: 3
    }
    first, _, last = await kept(async_db_session)
    sent = await MeetingsService(async_db_session, None).request(MEET)
    first.meeting_id = sent.id
    await async_db_session.commit()

    feeds.by_url["https://calendar/first"] = feed(
        STANDUP.replace("COUNT=3", "COUNT=1").replace("20261019T09", "20261020T09"),
        MOVED,
    )
    await read_calendars(async_db_session, feeds.read, NOW)

    rows = await kept(async_db_session)
    assert [(r.starts_at.day, r.starts_at.hour, r.cancelled) for r in rows] == [
        (19, 13, False),
        (20, 14, True),
    ]
    assert rows[0].meeting_id == sent.id
    assert last.id not in {r.id for r in rows}


async def test_another_agent_has_its_own_calendar(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kept under ``CALENDAR__<NAME>``. An agent with none is skipped, and
    one whose calendar cannot be read keeps what it had."""
    store = use_store(monkeypatch)
    store.values[f"{CALENDAR}__WORK"] = "https://calendar/work"
    work = await accounts.keep_agent(async_db_session, "work", "Work", None)
    feeds = Feeds()
    feeds.by_url["https://calendar/work"] = feed(STANDUP)

    assert await read_calendars(async_db_session, feeds.read, NOW) == {"work": 3}
    feeds.by_url["https://calendar/work"] = ConnectionError("down")
    assert await read_calendars(async_db_session, feeds.read, NOW) == {}

    rows = await kept(async_db_session)
    assert [r.account_id for r in rows] == [work.id] * 3
