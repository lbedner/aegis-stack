"""What a call threw up, in the Flet Overseer's meeting pane: a section per
kind of moment, each with who said it, a button per action it offers, and
what was asked of it; the pane follows a run still going."""

from typing import Any

import flet as ft

from app.components.frontend.dashboard.modals.meetings_moments import moments_controls
from tests.components.frontend._tree import texts


def _moment(**fields: Any) -> dict[str, Any]:
    return {
        "id": 5,
        "meeting_id": 11,
        "line_id": 42,
        "kind": "question",
        "title": "Questions",
        "text": "Can the CSV export ship this week?",
        "speaker": "Dana",
        "at": 12.0,
        "actions": [
            {
                "name": "copy",
                "label": "Copy for agent",
                "where": "browser",
                "prompt": "P",
            },
            {"name": "agent", "label": "Ask agent", "where": "runner", "prompt": None},
        ],
        "runs": [],
    } | fields


async def _nothing(*_: Any) -> None:
    return None


def _shown(*moments: dict[str, Any]) -> str:
    controls = moments_controls({"moments": list(moments)}, _nothing, _nothing)
    return " | ".join(texts(ft.Column(controls)))


def test_a_question_reads_with_its_actions() -> None:
    shown = _shown(_moment())

    assert "Questions" in shown and "Dana" in shown
    assert "Can the CSV export ship this week?" in shown
    assert "Copy for agent" in shown and "Ask agent" in shown


def test_each_run_says_where_it_stands_and_what_it_came_back_with() -> None:
    runs = [
        {
            "id": 1,
            "action": "agent",
            "label": "Ask agent",
            "status": "asked",
            "state": "Waiting for a runner",
            "result": None,
            "runner": None,
        },
        {
            "id": 2,
            "action": "agent",
            "label": "Ask agent",
            "status": "done",
            "state": "Answered on laptop",
            "result": "Yes: export.py ships it.",
            "runner": "laptop",
        },
    ]

    shown = _shown(_moment(runs=runs))

    assert "Waiting for a runner" in shown
    assert "Answered on laptop" in shown and "Yes: export.py ships it." in shown


def test_nothing_heard_shows_nothing() -> None:
    assert moments_controls({"moments": []}, _nothing, _nothing) == []
