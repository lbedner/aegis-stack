"""The Meetings card and modal in the Flet Overseer, minus the runtime:
the card's counts, a meeting's row, and one meeting read in full."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import flet as ft
import pytest

from app.components.frontend.controls import SectionCard
from app.components.frontend.dashboard.cards.meetings_card import MeetingsCard
from app.components.frontend.dashboard.modals import meetings_modal
from app.components.frontend.dashboard.modals.meetings_modal import (
    MeetingPane,
    actions_for,
    following,
    meeting_cells,
)
from app.components.frontend.dashboard.modals.meetings_people_tab import guide_view
from app.components.frontend.dashboard.modals.meetings_record import RecordView
from app.components.frontend.dashboard.modals.modal_sections.chart_primitives import (
    ChartColors,
)
from app.services.meetings.health import MEETINGS_MODAL_ID
from app.services.system.models import ComponentStatus, ComponentStatusType
from tests._meetings import MEET, record
from tests.components.frontend._tree import tab_names, tabs_in, texts, walk

MEETING = {
    "id": 7,
    "url": MEET,
    "status": "left",
    "bot_name": "Notes",
    "owner_user_id": 4242,
    "me": "Ada",
    "heard": {"Ada": 42.0},
    "created_at": "2026-10-12T19:00:00",
    "joined_at": "2026-10-12T19:00:30",
    "left_at": "2026-10-12T19:31:00",
}


def _record(**fields: Any) -> dict[str, Any]:
    """A meeting as the admin API reads it (``MeetingRecord``, as JSON)."""
    return record().model_dump(mode="json") | {"meeting": MEETING} | fields


def test_card_shows_the_counts_the_health_check_reports() -> None:
    status = ComponentStatus(
        name="meetings",
        status=ComponentStatusType.HEALTHY,
        message="5 meetings, 1 in a call",
        metadata={"meetings": 5, "in_call": 1},
    )

    card = MeetingsCard(status).build()

    # The card opens the modal registered under the same id: one constant.
    assert card.component_name == MEETINGS_MODAL_ID
    shown = texts(card)
    assert "5" in shown and "1" in shown


def test_a_row_says_whose_it_is_how_it_went_and_how_long() -> None:
    cells = meeting_cells(MEETING)

    assert MEET in cells and "4242" in cells and "Left" in cells
    assert "30:30" in cells
    assert meeting_cells(MEETING | {"title": "New Dev Call"})[0] == "New Dev Call"


def test_a_meeting_reads_with_its_notes_transcript_and_what_was_heard() -> None:
    record = _record(
        notes={
            "summary": "Ada writes the docs.",
            "decisions": [],
            "action_items": [
                {"text": "Write the docs", "owner": "Ada", "due": None, "lines": [3]}
            ],
            "open_questions": [],
        },
        model_name="test-model",
        transcript=[{"id": 3, "speaker": "Ada", "at": 61.0, "text": "I will."}],
    )

    shown = " | ".join(texts(RecordView(record)))

    for said in ("Ada writes the docs.", "Write the docs", "Ada 42s", "I will."):
        assert said in shown
    assert "01:01" in shown


NOTES = {
    "summary": "Ada writes the docs.",
    "decisions": [],
    "action_items": [],
    "open_questions": [],
}


def test_a_meeting_reads_in_tabs() -> None:
    """Its threads have a tab once its notes are there and settled."""
    assert tab_names(RecordView(_record())) == [
        "Overview",
        "Notes",
        "Moments",
        "Transcript",
    ]
    assert "Threads" in tab_names(RecordView(_record(notes=NOTES)))


def test_each_part_of_the_notes_is_its_own_card() -> None:
    view = RecordView(_record(notes=NOTES))
    cards = [n for n in walk(view.pages["Notes"]) if isinstance(n, SectionCard)]
    assert [texts(card)[0] for card in cards] == [
        "Summary",
        "Yours",
        "Action items",
        "Decisions",
        "Open questions",
    ]


def test_a_line_opens_the_transcript() -> None:
    said = [{"id": 3, "speaker": "Ada", "at": 1.0, "text": "Hi."}]
    view = RecordView(_record(transcript=said))
    view.open_at(3)
    assert view.picked == "Transcript"


def test_the_pane_keeps_its_tab_when_it_reads_again() -> None:
    """Followed, a meeting is drawn again every few seconds: the tab the
    reader is on stays open."""
    pane = MeetingPane(MagicMock(expires_at=None), on_change=AsyncMock())
    pane._draw(_record(notes=NOTES))
    tabs_in(pane).selected_index = 1  # the reader's click, as Flet keeps it

    pane._draw(_record(notes=NOTES))

    assert tabs_in(pane).picked == "Notes"


def test_each_speaker_and_owner_is_marked_in_their_color() -> None:
    """The meeting's color for each name (``voices``), as the htmx page's:
    on every line they said, and on the action items they own."""
    items = [{"text": "Send the deck", "owner": "Grace", "due": None, "lines": []}]
    view = RecordView(
        _record(
            notes=NOTES | {"action_items": items},
            transcript=[{"id": 3, "speaker": "Ada", "at": 1.0, "text": "Hi."}],
            voices={"Ada": 2, "Grace": 5},
        )
    )
    dots = [n.bgcolor for n in walk(view) if getattr(n, "data", None) == "voice"]
    assert ChartColors.RAMP[1] in dots and ChartColors.RAMP[4] in dots


def test_a_long_line_wraps_beside_its_clock() -> None:
    """Who said it and what take the width the clock leaves: a long line
    wraps there instead of running off the pane."""
    said = [{"id": 3, "speaker": "Ada", "at": 1.0, "text": "Long. " * 40}]
    view = RecordView(_record(transcript=said, voices={"Ada": 2}))
    (line,) = view.pages["Transcript"].controls
    clock, rest = line.controls
    assert clock.width and rest.expand


def test_notes_that_failed_say_why() -> None:
    record = _record(notes_error="the model is down")

    assert "the model is down" in " | ".join(texts(RecordView(record)))


def test_the_actions_are_the_ones_the_read_allows() -> None:
    assert actions_for(_record(can_leave=True, can_delete=False)) == ["leave"]
    assert actions_for(_record(can_leave=True)) == ["leave", "delete"]
    assert actions_for(_record(can_delete=False)) == []
    assert actions_for(_record(can_delete=False, can_look_over=True)) == ["look_over"]
    assert actions_for(_record()) == ["delete"]
    assert actions_for(_record(can_rewrite=True)) == ["delete", "rewrite"]


def test_my_items_come_first_once_i_say_which_speaker_i_am() -> None:
    mine = [{"text": "Write the docs", "owner": "Ada", "due": None, "lines": []}]
    notes = {"summary": "Docs.", "decisions": [], "action_items": mine}

    shown = " | ".join(texts(RecordView(_record(notes=notes, mine=mine))))
    unsaid = " | ".join(
        texts(RecordView(_record(notes=notes, meeting=MEETING | {"me": None})))
    )

    assert shown.index("Write the docs") < shown.index("Action items")
    assert "Say which speaker you are" in unsaid


def test_it_follows_a_meeting_while_something_is_happening() -> None:
    assert following(_record(following=True))
    assert not following(_record())


async def test_following_stops_once_the_modal_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A closed modal stops reading its meeting; a closed tab stops it too,
    after ``SessionLoops``' grace (that rule is the helper's, tested there)."""
    reads: list[Any] = []
    monkeypatch.setattr(meetings_modal, "api", lambda page: reads.append(page))
    monkeypatch.setattr(meetings_modal, "FOLLOW_SECONDS", 0.01)
    pane = MeetingPane(MagicMock(expires_at=None), on_change=AsyncMock())
    pane._showing = 7

    pane.will_unmount()
    await asyncio.wait_for(pane._follow(7), timeout=1)

    assert reads == []


def _guide(**fields: Any) -> dict[str, Any]:
    """A person's guide as the admin API reads it (``GuideRecord``)."""
    quote = {
        "id": 3,
        "meeting_id": 7,
        "speaker": "Ada",
        "at": 61.0,
        "text": "Numbers first.",
    }
    sections = [
        {"key": "cares_about", "title": "What they care about", "points": []},
        {
            "key": "information",
            "title": "How they like their information",
            "points": [{"text": "The numbers first", "quotes": [quote]}],
        },
    ]
    guide = {"id": 1, "person": "Ada", "owner_user_id": 4242, "meetings": 3}
    return {
        "guide": guide | fields.pop("guide", {}),
        "sections": sections,
        "writing": False,
        "can_write": True,
    } | fields


def test_a_guide_reads_with_the_lines_each_point_rests_on() -> None:
    view = guide_view(_guide())
    shown = " | ".join(texts(view))
    # The lines fold under the point, closed until it is opened.
    (point,) = [c for c in walk(view) if isinstance(c, ft.ExpansionTile)]
    lines = " | ".join(texts(point))

    assert "How they like their information" in shown
    assert "Nothing yet." in shown
    assert texts(point.title) == ["The numbers first"]
    assert not point.initially_expanded
    assert "Numbers first." in lines and "Meeting 7, 01:01" in lines


def test_a_guide_that_failed_says_why() -> None:
    record = _guide(guide={"error": "the model is down"})

    assert "the model is down" in " | ".join(texts(guide_view(record)))
