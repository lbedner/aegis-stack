"""The Flet Overseer's voice profiles, as the htmx Profiles tab: every
profile at a glance (``/api/v1/voice/design/profiles``), and one opened in
the three-step editor (Voice, Delivery, Review) over the API. The server
sends the editor whole (``design_view``): the voices narrowed, the dials
the model takes, the design as form fields; the editor draws it and asks
again on every pick and filter."""

from typing import Any

import flet as ft
import pytest

pytest.importorskip("app.services.ai.domains.voice", reason="no voice in this stack")

from app.components.frontend.dashboard.modals.voice_settings import (  # noqa: E402
    designer,
    profiles,
)

MARIN = {
    "id": "marin",
    "name": "Marin",
    "provider": "openai",
    "provider_name": "OpenAI",
    "gender": "female",
    "tone": "Warm",
    "family": "warm",
    "accent": "General American",
    "language": "English",
    "detail": "Warm · female · General American · OpenAI",
    "description": "",
}
CEDAR = MARIN | {"id": "cedar", "name": "Cedar", "gender": "male"}


def _option(name: str, value: str, checked: bool = False, indent: bool = False) -> dict:
    return {
        "name": name,
        "value": value,
        "label": value,
        "checked": checked,
        "indent": indent,
    }


VIEW: dict[str, Any] = {
    "profile": {"id": 3, "name": "Hers"},
    "active": True,
    "steps": {"voice": "Voice", "delivery": "Delivery", "review": "Review"},
    "chosen": MARIN,
    "find": {
        "q": "",
        "filters": {
            "provider": ["openai"],
            "gender": [],
            "family": [],
            "language": [],
            "accent_of": ["General American"],
        },
        "options": {
            "provider": [_option("provider", "openai", True)],
            "gender": [_option("gender", "female"), _option("gender", "male")],
            "family": [_option("family", "warm")],
            "accent": [
                _option("language", "English"),
                _option("accent_of", "General American", True, indent=True),
            ],
        },
        "cards": [CEDAR],
        "matched": 40,
        "limit": 50,
    },
    "locked": [{"provider_name": "Gemini", "voices": 30, "key": "GOOGLE_API_KEY"}],
    "logos": {},
    "styles": {
        "": {"label": "Plain", "sounds": "No style; just the dials", "dials": {}},
        "calm": {
            "label": "Calm and warm",
            "sounds": "Calm; friendly",
            "dials": {"pace": "slow", "energy": "low", "emotion": "warm"},
        },
    },
    "dials": {"pace": {"slow": "Slow", "natural": "Natural"}},
    "steers_accent": True,
    "voice": "marin",
    "model": "gpt-realtime-2.1-mini",
    "models": [{"id": "gpt-realtime-2.1-mini", "note": "Reads", "instructions": True}],
    "follows": True,
    "delivery": {
        "style": "calm",
        "pace": "slow",
        "energy": "low",
        "emotion": "warm",
        "accent": "none",
        "extra": None,
    },
    "speed": 1.0,
    "speed_range": [0.25, 1.5],
    "tuned": False,
    "instructions": "Voice Affect: Calm.",
    "form": {"voice": "marin", "style": "calm", "pace": "slow", "was_style": "calm"},
}


def _editor(view: dict[str, Any] = VIEW) -> designer.VoiceEditor:
    editor = designer.VoiceEditor(3, back=lambda: None)
    editor._view = view
    return editor


def _found(control: Any, kind: type) -> list[Any]:
    """Every ``kind`` control under ``control``."""
    found = [control] if isinstance(control, kind) else []
    for child in getattr(control, "controls", None) or []:
        found += _found(child, kind)
    if (content := getattr(control, "content", None)) is not None:
        found += _found(content, kind)
    return found


def test_a_pick_or_a_filter_is_the_query_the_server_reads() -> None:
    query = _editor()._query(pace="natural", gender=["male"])

    assert query["voice"] == "marin" and query["pace"] == "natural"
    assert query["was_style"] == "calm"  # a style kept, so the dials stay as picked
    assert query["gender"] == ["male"] and query["provider"] == ["openai"]
    assert query["filtered"] == "1"  # so a cleared filter stays cleared


def test_the_accent_dropdown_is_grouped_by_language() -> None:
    choices = designer.accent_choices(VIEW["find"]["options"]["accent"])

    assert list(choices.values()) == ["Any", "English (all)", "    General American"]
    assert designer.accent_picked("language:English") == {
        "language": ["English"],
        "accent_of": [],
    }
    assert designer.accent_picked("") == {"language": [], "accent_of": []}


async def test_save_posts_the_design_to_its_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posted: list[tuple[str, Any]] = []

    class Api:
        async def post(self, path: str, json: Any = None) -> Any:
            posted.append((path, json))
            return VIEW

    editor = _editor()
    monkeypatch.setattr(editor, "_api", Api)
    back: list[bool] = []
    editor._back = lambda: back.append(True)

    await editor._save()

    assert back == [True]  # back to the profiles
    path, body = posted[0]
    assert path == "/api/v1/voice/design?profile=3"
    assert body["voice"] == "marin" and body["delivery"]["style"] == "calm"


def test_the_editor_walks_the_steps_it_is_sent() -> None:
    editor = _editor()
    shown: list[str] = []
    editor._show = lambda view: shown.append(editor._step)  # type: ignore[method-assign]

    editor._go("delivery")
    editor._go("review")

    assert shown == ["delivery", "review"]


def test_a_profile_row_says_its_voice_style_speed_and_whether_in_use() -> None:
    cells = profiles.VoiceProfiles()._cells(
        {
            "id": 3,
            "name": "Hers",
            "voice": "Marin",
            "style": "Plain",
            "speed": 1.1,
            "active": True,
        }
    )

    assert cells[:4] == ["Hers", "Marin", "Plain", "1.1"]


def test_the_voice_step_pins_the_chosen_and_draws_the_search() -> None:
    who = _editor()._who()

    assert [r.value for r in _found(who, ft.Radio)] == ["marin", "cedar"]
    assert [d.value for d in _found(who, ft.Dropdown)][:4] == [
        "openai",
        "",
        "",
        "accent_of:General American",
    ]
    said = [t.value for t in _found(who, ft.Text) if t.visible]
    assert any("The first 1 of 40" in (v or "") for v in said)


def test_the_delivery_step_says_who_was_picked() -> None:
    chosen = next(c for c in _editor()._how().controls if c.data == "chosen")

    assert chosen.controls[1].value == "Marin"


def test_a_model_that_ignores_instructions_is_said_on_delivery() -> None:
    editor = _editor(VIEW | {"follows": False})

    ignores = next(c for c in editor._how().controls if c.data == "ignores")

    assert ignores.visible is True


def test_speed_is_offered_only_where_the_model_takes_one() -> None:
    assert _found(_editor()._how(), ft.Slider)
    assert not _found(_editor(VIEW | {"speed_range": None})._how(), ft.Slider)


def test_fine_tune_stays_open_as_the_editor_redraws() -> None:
    editor = _editor()

    def tile() -> Any:
        return _found(editor._how(), ft.ExpansionTile)[0]

    assert tile().initially_expanded is False
    tile().on_change(type("Event", (), {"data": "true"})())

    assert tile().initially_expanded is True  # a pick redraws it open


async def test_editing_opens_fine_tune_on_what_was_tuned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Api:
        async def get(self, path: str) -> Any:
            return VIEW | {"tuned": True}

    editor = designer.VoiceEditor(3, back=lambda: None)
    monkeypatch.setattr(editor, "_api", Api)
    monkeypatch.setattr(editor, "_show", lambda view: setattr(editor, "_view", view))

    await editor.load({})

    assert _found(editor._how(), ft.ExpansionTile)[0].initially_expanded is True


def test_each_voice_wears_its_providers_mark() -> None:
    from app.components.frontend.controls.provider_icon import ProviderIcon

    editor = _editor(
        VIEW | {"logos": {"openai": {"org": "openai", "icon": "iVBORw0KGgo="}}}
    )

    marks = _found(editor._who(), ProviderIcon)
    assert len(marks) == 2  # the chosen one and the one listed
