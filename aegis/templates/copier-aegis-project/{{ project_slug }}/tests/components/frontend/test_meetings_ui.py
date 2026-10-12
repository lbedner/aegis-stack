"""The Meetings card and modal in the Flet Overseer, minus the runtime:
the card's counts, a meeting's row, and one meeting read in full."""

from typing import Any

from app.components.frontend.dashboard.cards.meetings_card import MeetingsCard
from app.components.frontend.dashboard.modals.meetings_modal import (
    actions_for,
    meeting_cells,
    record_view,
)
from app.services.meetings.health import MEETINGS_MODAL_ID
from app.services.system.models import ComponentStatus, ComponentStatusType
from tests._meetings import MEET
from tests.components.frontend._tree import texts

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
    """A meeting as the admin API reads it (``MeetingRecord``)."""
    return {
        "meeting": MEETING,
        "notes": None,
        "notes_error": None,
        "model_name": None,
        "transcript": [],
        "status": "Left",
        "length": "30:30",
        "heard": "Ada 42s",
        "can_leave": False,
        "can_delete": True,
    } | fields


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

    shown = " | ".join(texts(record_view(record)))

    for said in ("Ada writes the docs.", "Write the docs", "Ada 42s", "I will."):
        assert said in shown
    assert "01:01" in shown


def test_notes_that_failed_say_why() -> None:
    record = _record(notes_error="the model is down")

    assert "the model is down" in " | ".join(texts(record_view(record)))


def test_the_actions_are_the_ones_the_read_allows() -> None:
    assert actions_for(_record(can_leave=True, can_delete=False)) == ["leave"]
    assert actions_for(_record(can_leave=True)) == ["leave", "delete"]
    assert actions_for(_record(can_delete=False)) == []
    assert actions_for(_record()) == ["delete"]
