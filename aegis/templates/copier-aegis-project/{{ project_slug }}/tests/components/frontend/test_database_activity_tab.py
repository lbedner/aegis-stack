"""The Flet database modal's Slow & locked tab: the last hour by the code
behind it, the summary the database health carries (``db_activity.summary``),
as Overseer's Slow & locked groups it (``ui_database.activity_groups``)."""

from app.components.frontend.dashboard.modals.database_modal.activity import (
    ActivityTab,
)
from app.services.system.models import ComponentStatus
from tests.components.frontend._fakes import FakePage
from tests.components.frontend._tree import texts

GROUP = {
    "code": "app/services/ai/chat.py:88 in stream_turn",
    "count": 3,
    "held_s": 41.5,
    "longest_s": 34.2,
    "last": "2026-10-02T12:00:00+00:00",
    "kinds": ["slow"],
    "processes": ["webserver"],
}


def _tab(by_code: list[dict], window: int = 3600) -> ActivityTab:
    summary = {"window_s": window, "slow_after_s": 2.0, "by_code": by_code}
    database = ComponentStatus(
        name="database", message="", metadata={"activity": summary}
    )
    return ActivityTab(database, FakePage())  # type: ignore[arg-type]


def test_a_code_site_shows_its_count_time_held_and_process() -> None:
    shown = " ".join(texts(_tab([GROUP])))
    assert "chat.py:88 in stream_turn" in shown
    assert "41s" in shown and "34s" in shown and "webserver" in shown


def test_nothing_recorded_says_so_for_the_window_it_covers() -> None:
    shown = texts(_tab([], window=1800))
    assert "Nothing slow or locked in the last 30 minutes" in shown
