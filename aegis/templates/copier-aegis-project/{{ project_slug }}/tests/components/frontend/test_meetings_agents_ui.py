"""Meetings > Agents in the Flet Overseer, minus the runtime: an agent's
row, the picker the bot is sent with, which agent a meeting was, the
picker a meeting or an agent's calendar meetings are given with, and an
agent's card in a call."""

from typing import Any

import flet as ft
import pytest

from app.components.frontend.dashboard.modals import meetings_agent_card
from app.components.frontend.dashboard.modals.meetings_agent_card import AgentCard
from app.components.frontend.dashboard.modals.meetings_agents_tab import (
    AgentPicker,
    agent_cells,
)
from app.components.frontend.dashboard.modals.meetings_modal import meeting_cells
from app.components.frontend.dashboard.modals.meetings_owners import OwnerPicker
from app.services.meetings.domains.accounts.service import agent_names
from tests._meetings import PIXEL_PNG

WORK: dict[str, Any] = {
    "account": {
        "id": 2,
        "name": "work",
        "display_name": "Work Notes",
        "email": "notes@work.example",
        "camera": True,
        "answers_anyone": True,
    },
    "sign_in": "Signed in",
    "in_now": [7, 9],
    "image": None,
    "initials": "WN",
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


def test_the_owner_picker_offers_everyone_here_and_nobody() -> None:
    picked: list[int | None] = []
    owners = [{"id": 3, "email": "leo@example.com"}]

    picker = OwnerPicker("Default owner", owners, 3, picked.append)

    assert [(o.key, o.text) for o in picker.options or []] == [
        ("", "Nobody"),
        ("3", "leo@example.com"),
    ]
    assert picker.value == "3" and picker.visible
    assert not OwnerPicker("Default owner", [], None, picked.append).visible


async def _nothing() -> None:
    return None


def test_an_agents_card_shows_its_initials_until_it_has_a_picture() -> None:
    plain = AgentCard(None, WORK, None, _nothing)  # type: ignore[arg-type]
    pictured = AgentCard(
        None, WORK | {"image": "2026-10-23T00:00:00"}, PIXEL_PNG, _nothing
    )  # type: ignore[arg-type]

    assert not any(isinstance(c, ft.Image) for c in plain.controls)
    assert any(isinstance(c, ft.Image) for c in pictured.controls)
    assert plain.switches["camera"].value is True
    assert plain.switches["answers_anyone"].value is True


class _Refused:
    """The admin API refusing whatever it is asked."""

    async def request_with_status(self, *args: Any, **kwargs: Any) -> tuple[int, Any]:
        return 422, {"detail": "A card takes GIF, JPEG, PNG, SVG, WEBP"}


def _said(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    said: list[str] = []

    class Said:
        def __init__(self, text: str) -> None:
            said.append(text)

        def launch(self, page: Any) -> None:
            return None

    monkeypatch.setattr(meetings_agent_card, "api", lambda page: _Refused())
    monkeypatch.setattr(meetings_agent_card, "ErrorSnackBar", Said)
    return said


async def test_a_picture_the_card_cannot_take_says_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    said = _said(monkeypatch)
    reloaded: list[bool] = []

    async def changed() -> None:
        reloaded.append(True)

    card = AgentCard(None, WORK, None, changed)  # type: ignore[arg-type]
    await card._upload("notes.pdf", b"%PDF")

    assert said == ["A card takes GIF, JPEG, PNG, SVG, WEBP"] and not reloaded


async def test_a_switch_that_fails_to_change_is_put_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    said = _said(monkeypatch)
    card = AgentCard(None, WORK, None, _nothing)  # type: ignore[arg-type]
    card.switches["answers_anyone"].value = False

    await card._switch("answers_anyone", False)

    assert card.switches["answers_anyone"].value is True and said
