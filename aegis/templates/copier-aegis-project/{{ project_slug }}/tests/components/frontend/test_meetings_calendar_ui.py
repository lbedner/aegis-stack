"""Meetings > Calendar in the Flet Overseer, minus the runtime: the month it
asks the admin API for, and each day's meetings as lines."""

from datetime import date
from typing import Any

from app.components.frontend.dashboard.modals.meetings_calendar_tab import (
    by_day,
    entry_line,
    month_params,
)

STANDUP: dict[str, Any] = {
    "agent": "notetaker",
    "color": 3,
    "title": "Standup",
    "starts_at": "2026-10-19T13:00:00Z",
    "ends_at": "2026-10-19T13:15:00Z",
    "state": "upcoming",
}


def test_a_month_asks_for_its_whole_weeks_in_utc() -> None:
    assert month_params(date(2026, 10, 18)) == {
        "first": "2026-09-28",
        "last": "2026-11-01",
        "tz": "UTC",
    }


def test_each_day_lists_its_meetings_as_lines_in_order() -> None:
    later = STANDUP | {"title": "Review", "starts_at": "2026-10-19T15:30:00Z"}

    days = by_day([later, STANDUP])

    assert [entry_line(e) for e in days[date(2026, 10, 19)]] == [
        "13:00 Standup",
        "15:30 Review",
    ]
