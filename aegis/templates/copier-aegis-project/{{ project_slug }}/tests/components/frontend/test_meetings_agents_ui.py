"""Meetings > Agents in the Flet Overseer, minus the runtime: an agent's
row, the picker the bot is sent with, and which agent a meeting was."""

from typing import Any

from app.components.frontend.dashboard.modals.meetings_agents_tab import (
    AgentPicker,
    agent_cells,
)
from app.components.frontend.dashboard.modals.meetings_modal import meeting_cells
from app.services.meetings.domains.accounts.service import agent_names

WORK: dict[str, Any] = {
    "account": {
        "id": 2,
        "name": "work",
        "display_name": "Work Notes",
        "email": "notes@work.example",
    },
    "sign_in": "Signed in",
    "in_now": [7, 9],
}
FIRST: dict[str, Any] = {
    "account": {"id": 1, "name": "notetaker", "display_name": "Notetaker"},
    "sign_in": "Not signed in",
    "in_now": [],
}


def test_an_agent_says_who_it_is_its_sign_in_and_where_it_is() -> None:
    cells = agent_cells(WORK)

    assert cells[:4] == ["work", "Work Notes", "notes@work.example", "Signed in"]
    assert cells[4] == "Meeting 7, Meeting 9"
    assert agent_cells(FIRST)[2] == "-" and agent_cells(FIRST)[4] == "-"


def test_a_meeting_row_names_its_agent() -> None:
    meeting = {"id": 7, "url": "https://meet.google.com/x", "account_id": 2}

    names = agent_names(
        (a["account"]["id"], a["account"]["name"]) for a in [FIRST, WORK]
    )
    assert "work" in meeting_cells(meeting, names)


def test_the_picker_shows_only_when_there_is_a_choice() -> None:
    picker = AgentPicker()

    picker.fill([FIRST])
    assert not picker.visible and picker.chosen() == {}

    picker.fill([FIRST, WORK])
    assert picker.visible
    assert [o.key for o in picker.options] == ["notetaker", "work"]
    assert picker.chosen() == {"agent": "notetaker"}
    picker.value = "work"
    assert picker.chosen() == {"agent": "work"}
