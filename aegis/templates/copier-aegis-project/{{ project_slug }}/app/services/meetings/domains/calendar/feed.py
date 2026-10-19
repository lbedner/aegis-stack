"""An agent's calendar as Google's iCal feed has it: each meeting on it,
one per time it happens, with the link the agent joins by."""

from datetime import datetime
import re
from typing import Any

import httpx
from icalendar import Calendar
from pydantic import BaseModel, ConfigDict
import recurring_ical_events

from app.core.time import as_stored
from app.services.meetings.service import UnsupportedMeetingLinkError, detect_platform

LINK = re.compile(r"https://[^\s<>\"']+")
READ_SECONDS = 30


class CalendarMeeting(BaseModel):
    """One time a meeting happens. ``key`` is its event's UID and the time
    it was first set for, so a time moved or cancelled on its own is still
    the same one. Times are naive UTC, as the columns keep them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    title: str
    starts_at: datetime
    ends_at: datetime
    url: str | None
    organizer: str | None
    emails: list[str]
    cancelled: bool


async def read_feed(url: str) -> str:
    """The calendar at ``url``. Raises httpx's errors, which name the
    address: a secret, so a caller logs the error's type, never its text."""
    async with httpx.AsyncClient(timeout=READ_SECONDS) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


def meetings_between(ics: str, start: datetime, end: datetime) -> list[CalendarMeeting]:
    """The meetings in ``ics`` from ``start`` to ``end``, earliest first; a
    day-long event is not one."""
    events = recurring_ical_events.of(Calendar.from_ical(ics)).between(start, end)
    found = [_meeting(e) for e in events if isinstance(e.decoded("DTSTART"), datetime)]
    return sorted(found, key=lambda m: m.starts_at)


def _meeting(event: Any) -> CalendarMeeting:
    first_set = as_stored(event.decoded("RECURRENCE-ID", event.decoded("DTSTART")))
    return CalendarMeeting(
        key=f"{event['UID']}|{first_set:%Y%m%dT%H%M%SZ}",
        title=str(event.get("SUMMARY", "")),
        starts_at=as_stored(event.decoded("DTSTART")),
        ends_at=as_stored(event.decoded("DTEND", event.decoded("DTSTART"))),
        url=_link(event),
        organizer=_organizer(event.get("ORGANIZER")),
        emails=_emails(event),
        cancelled=str(event.get("STATUS", "")).upper() == "CANCELLED",
    )


def _link(event: Any) -> str | None:
    """The conference Google attached, else the first meeting link in the
    location or description (one the bot may not join yet)."""
    text = f"{event.get('LOCATION', '')}\n{event.get('DESCRIPTION', '')}"
    for url in [str(event.get("X-GOOGLE-CONFERENCE", "")), *LINK.findall(text)]:
        try:
            detect_platform(url)
        except UnsupportedMeetingLinkError:
            continue
        return url
    return None


def _address(prop: Any) -> str:
    """A calendar address's email: ``mailto:dana@example.com``."""
    return str(prop).removeprefix("mailto:").lower()


def _organizer(organizer: Any) -> str | None:
    if organizer is None:
        return None
    return organizer.params.get("CN") or _address(organizer)


def _emails(event: Any) -> list[str]:
    """Every email on the invite, the organizer's first, lowercased: one
    attendee is a value, several a list."""
    attendees = event.get("ATTENDEE", [])
    if not isinstance(attendees, list):
        attendees = [attendees]
    found = [event.get("ORGANIZER"), *attendees]
    emails = (_address(a) for a in found if a is not None)
    return list(dict.fromkeys(e for e in emails if "@" in e))
