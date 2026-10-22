"""What a call threw up, in the Flet Overseer's meeting pane: a section per
kind of moment, each with who said it, a button per action it offers, and
what was asked of it; the pane follows a run still going."""

from typing import Any

import flet as ft

from app.components.frontend.dashboard.modals.meetings_moments import moments_controls
from tests.components.frontend._tree import texts, walk


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


def test_a_card_cleaned_up_reads_under_its_topic() -> None:
    assert "Scale returns" in _shown(_moment(topic="Scale returns"))


def test_a_burst_reads_as_one_question_with_its_follow_ups() -> None:
    follow = _moment(id=6, line_id=43, text="Did billing sign off on it?")

    shown = _shown(_moment(also=[follow]))

    assert "Can the CSV export ship this week?" in shown
    assert "Did billing sign off on it?" in shown


def test_each_run_says_where_it_stands_and_what_it_came_back_with() -> None:
    runs = [
        {
            "id": 1,
            "action": "agent",
            "label": "Ask agent",
            "status": "asked",
            "state": "Waiting for a runner",
            "tone": "muted",
            "result": None,
            "runner": None,
        },
        {
            "id": 2,
            "action": "agent",
            "label": "Ask agent",
            "status": "done",
            "state": "Answered on laptop",
            "tone": "ok",
            "result": "Yes: export.py ships it.",
            "runner": "laptop",
        },
    ]

    shown = _shown(_moment(runs=runs))

    assert "Waiting for a runner" in shown
    assert "Answered on laptop" in shown and "Yes: export.py ships it." in shown


def test_nothing_heard_shows_nothing() -> None:
    assert moments_controls({"moments": []}, _nothing, _nothing) == []


def _tile(
    moment: dict[str, Any], folds: dict[int, bool] | None = None
) -> ft.ExpansionTile:
    controls = moments_controls({"moments": [moment]}, _nothing, _nothing, folds)
    (tile,) = (c for c in walk(ft.Column(controls)) if isinstance(c, ft.ExpansionTile))
    return tile


def test_a_question_folds_away_unless_it_is_being_answered() -> None:
    """Folded to what was asked; open while an answer is going, or as the
    reader last left it (``folds``, kept across the pane's redraws)."""
    going = {
        "id": 1,
        "label": "Ask agent",
        "status": "claimed",
        "state": "Answering on laptop",
        "tone": "muted",
        "going": True,
    }

    assert not _tile(_moment()).initially_expanded
    assert "Can the CSV export ship this week?" in texts(_tile(_moment()).title)
    assert _tile(_moment(runs=[going])).initially_expanded
    assert _tile(_moment(), folds={5: True}).initially_expanded
    assert not _tile(_moment(runs=[going]), folds={5: False}).initially_expanded
