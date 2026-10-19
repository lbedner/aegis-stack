"""Meetings > Search in the Flet Overseer, minus the runtime: the words
searched across every owner's meetings, a hit's row, and the meeting it
opens marked at its line."""

from unittest.mock import AsyncMock, MagicMock

import flet as ft
import pytest

from app.components.frontend.dashboard.modals import meetings_search_tab
from app.components.frontend.dashboard.modals.meetings_modal import record_view
from app.components.frontend.dashboard.modals.meetings_search_tab import (
    SearchTab,
    hit_cells,
)
from tests._meetings import record
from tests.components.frontend._tree import texts, walk

HIT = {
    "meeting_id": 7,
    "part": "Transcript",
    "speaker": "Lawrence",
    "line_id": 3,
    "at": 61.0,
    "text": "Our pricing is too low.",
}


def test_a_hit_says_where_who_and_what() -> None:
    assert hit_cells(HIT) == ["Meeting 7, 01:01", "Lawrence", "Our pricing is too low."]
    noted = HIT | {"part": "Decisions", "speaker": None, "line_id": None, "at": None}
    assert hit_cells(noted) == ["Meeting 7", "Decisions", "Our pricing is too low."]


def test_the_meeting_opens_marked_at_the_hits_line() -> None:
    transcript = [
        {"id": 2, "speaker": "Ada", "at": 60.0, "text": "Hello."},
        {"id": 3, "speaker": "Lawrence", "at": 61.0, "text": "Our pricing is too low."},
    ]
    read = record().model_dump(mode="json") | {"transcript": transcript}

    lines = {c.key: c for c in walk(record_view(read, hit=3)) if c.key}

    assert lines["line-3"].weight == ft.FontWeight.BOLD
    assert lines["line-2"].weight != ft.FontWeight.BOLD


async def test_the_words_search_every_owner_and_a_hit_opens_its_meeting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = MagicMock(get=AsyncMock(return_value=[HIT]))
    monkeypatch.setattr(meetings_search_tab, "api", lambda page: api)
    pane = MagicMock(show=AsyncMock())
    tab = SearchTab(MagicMock(), pane)
    tab._words.value = " pricing "

    await tab.search()

    api.get.assert_awaited_once_with(meetings_search_tab.API, params={"q": "pricing"})
    assert "Our pricing is too low." in texts(tab._table)
    await tab._open(0)
    pane.show.assert_awaited_once_with(7, line=3)
