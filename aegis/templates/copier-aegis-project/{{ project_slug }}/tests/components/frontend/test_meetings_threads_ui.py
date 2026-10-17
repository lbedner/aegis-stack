"""Commitments, contradictions and positions in the Flet Overseer: drawn
from the API's sections (``ThreadSection``), on a meeting's pane and on a
person's guide."""

from typing import Any

import flet as ft

from app.components.frontend.dashboard.modals.meetings_people_tab import guide_view
from app.components.frontend.dashboard.modals.meetings_threads import thread_controls
from tests.components.frontend._tree import texts, walk

QUOTE = {
    "id": 3,
    "meeting_id": 7,
    "speaker": "Ada",
    "at": 61.0,
    "text": "I'll send it.",
}
LATER = {"id": 9, "meeting_id": 8, "speaker": "Ada", "at": 5.0, "text": "Sent it."}


def _sections(**items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The person's sections as the API reads them, ``items`` by key."""
    titles = {
        "promised": ("They said they would", "Came up again"),
        "promised_them": ("Promised to them", "Came up again"),
    }
    return [
        {
            "key": key,
            "title": title,
            "other": other,
            "empty": "Nothing yet.",
            "items": items.get(key, []),
        }
        for key, (title, other) in titles.items()
    ]


def _deck(**fields: Any) -> dict[str, Any]:
    return {
        "text": "Send the deck",
        "meeting_id": 7,
        "speaker": "Ada",
        "detail": "by Friday",
        "status": "done",
        "quotes": [QUOTE],
        "other": [LATER],
    } | fields


def test_each_thread_reads_with_its_lines_and_where_it_came_up_again() -> None:
    controls = thread_controls(_sections(promised=[_deck()]))
    shown = " | ".join(t for c in controls for t in texts(c))
    (item,) = [c for c in controls for c in walk(c) if isinstance(c, ft.ExpansionTile)]
    lines = " | ".join(texts(item))

    assert "They said they would" in shown and "Nothing yet." in shown
    assert "Send the deck" in shown and "Done" in shown and "by Friday" in shown
    assert not item.initially_expanded
    assert "I'll send it." in lines and "Meeting 7, 01:01" in lines
    assert "Came up again" in lines and "Sent it." in lines


def test_a_guide_reads_with_the_persons_threads() -> None:
    record = {
        "guide": {"id": 1, "person": "Ada", "owner_user_id": 4242, "meetings": 2},
        "sections": [],
        "threads": _sections(promised=[_deck(other=[])]),
        "writing": False,
        "can_write": True,
    }

    shown = " | ".join(texts(guide_view(record)))

    assert "They said they would" in shown and "Send the deck" in shown
