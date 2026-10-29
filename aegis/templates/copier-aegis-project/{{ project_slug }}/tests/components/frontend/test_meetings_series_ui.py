"""Meetings > Series in the Flet Overseer: each series a row, one read in
its pane (its summary over time, then what it keeps coming back to), drawn
from the admin API's ``SeriesRow`` and ``SeriesRecord``."""

from typing import Any
from unittest.mock import MagicMock

from app.components.frontend.controls import SectionCard
from app.components.frontend.dashboard.modals.meetings_series_tab import (
    SeriesPane,
    series_cells,
    series_view,
)
from tests.components.frontend._tree import tab_names, tabs_in, texts, walk

SERIES = {
    "id": 5,
    "owner_user_id": 7,
    "link": "https://meet.google.com/abc-defg-hij",
    "name": "Dev call",
    "summary": "Dana keeps asking for the report.",
    "meetings": 3,
    "error": None,
    "model_name": "test-model",
    "written_at": "2026-10-19T15:00:00",
}
THEME = {
    "meeting_id": 11,
    "text": "The usage report",
    "speaker": "Dana",
    "detail": "3 meetings",
    "status": "open",
    "quotes": [
        {"id": 1, "meeting_id": 11, "speaker": "Dana", "at": 5.0, "text": "Report?"}
    ],
    "other": [],
}


def _record(**fields: Any) -> dict[str, Any]:
    return {
        "series": SERIES,
        "name": "Dev call",
        "meetings": [14, 11],
        "over_time": [
            {
                "key": "still_open",
                "title": "Still open",
                "other": None,
                "empty": "",
                "items": [THEME | {"detail": "Since meeting 11", "status": None}],
            }
        ],
        "sections": [
            {
                "key": "themes",
                "title": "Keeps coming up",
                "other": None,
                "empty": "Nothing yet.",
                "items": [THEME],
            }
        ],
        "writing": False,
        "can_write": True,
    } | fields


def test_a_series_row_says_what_it_is_whose_and_how_many_meetings() -> None:
    cells = series_cells({"series": SERIES, "name": "Dev call"})

    assert cells[:3] == ["Dev call", "7", "3"]


def test_a_series_reads_with_its_summary_and_its_themes() -> None:
    pane = SeriesPane(MagicMock())
    pane.draw(_record())
    shown = " | ".join(texts(pane))

    assert "Dev call" in shown and "Dana keeps asking for the report." in shown
    assert "Still open" in shown and "Since meeting 11" in shown
    assert "Keeps coming up" in shown and "The usage report" in shown
    assert "Open" in shown and "3 meetings" in shown


def test_a_failed_write_and_one_under_way_are_said() -> None:
    failed = {**SERIES, "error": "model down"}
    shown = " | ".join(texts(series_view(_record(series=failed, writing=True))))

    assert "The last write failed: model down" in shown
    assert "Writing the series…" in shown


def test_a_series_reads_in_tabs() -> None:
    assert tab_names(series_view(_record())) == ["Overview", "Over time", "Themes"]


def test_each_part_of_a_series_is_its_own_card() -> None:
    tabs = tabs_in(series_view(_record()))
    titles = {
        tab.text: [texts(c)[0] for c in walk(tab) if isinstance(c, SectionCard)]
        for tab in tabs.tabs
    }
    assert titles["Overview"] == ["Details", "Summary"]
    assert titles["Over time"] == ["Still open"]
    assert titles["Themes"] == ["Keeps coming up"]


def test_the_series_pane_keeps_its_tab_when_it_reads_again() -> None:
    """Followed while it is written, a series is drawn again: the tab the
    reader is on stays open."""
    pane = SeriesPane(MagicMock())
    pane.draw(_record())
    tabs_in(pane).selected_index = 2  # the reader's click, as Flet keeps it

    pane.draw(_record())

    assert tabs_in(pane).picked == "Themes"
