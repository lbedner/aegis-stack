"""Where a meeting stands, as the htmx pages show it: a badge in its tone.
The meetings list, a meeting's page and the calendar read the one map:
a call's status (``MeetingStatus``) or a calendar meeting's state
(``domains.calendar.entries``), the rest muted."""

from app.services.meetings.domains.calendar.entries import (
    CANNOT_JOIN,
    MISSED,
    UPCOMING,
    state_label,
)
from app.services.meetings.models import MeetingStatus

from .rendering import status_cell

TONES = {
    MeetingStatus.JOINING: "accent",
    MeetingStatus.WAITING: "warn",
    MeetingStatus.IN_CALL: "ok",
    MeetingStatus.LEAVING: "accent",
    MeetingStatus.FAILED: "error",
    UPCOMING: "accent",
    MISSED: "warn",
    CANNOT_JOIN: "warn",
}


def state_cell(state: str) -> dict[str, str]:
    """``state`` as a badge: its words, in its tone."""
    return status_cell(state_label(state), TONES.get(state, "muted"))
