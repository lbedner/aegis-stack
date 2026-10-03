"""The Flet database modal's Activity tab: the same rows as the Overseer's
Activity section (``ui_database.activity``)."""

from app.components.frontend.dashboard.modals.database_modal.activity import (
    ActivityTab,
)
from app.services.system.models import ComponentStatus
from tests.components.frontend._fakes import FakePage
from tests.components.frontend._tree import texts

EVENT = {
    "kind": "slow",
    "seconds": 34.2,
    "process": "webserver:7",
    "caller": "app/services/ai/chat.py:88 in stream_turn",
    "at": "2026-10-02T12:00:00+00:00",
}


def _tab(activity: list[dict]) -> ActivityTab:
    database = ComponentStatus(
        name="database", message="", metadata={"activity": activity}
    )
    return ActivityTab(database, FakePage())  # type: ignore[arg-type]


def test_a_slow_transaction_shows_its_length_and_caller() -> None:
    shown = " ".join(texts(_tab([EVENT])))
    assert "34.2" in shown and "chat.py:88 in stream_turn" in shown
    assert "webserver:7" in shown


def test_nothing_recorded_says_so() -> None:
    assert any("Nothing" in t for t in texts(_tab([])))
