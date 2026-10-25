"""The Flet Overseer's voice tab, as the htmx page: the voice overview's
rows (``/api/v1/voice/overview``) narrowed by kind, provider and text, each
playing its own voice on its own model, and Use putting a row on the
active profile over the API."""

from typing import Any

import pytest

pytest.importorskip("app.services.ai.domains.voice", reason="no voice in this stack")

from app.components.frontend.dashboard.modals.voice_settings import tab  # noqa: E402

KORE: dict[str, Any] = {
    "kind": "voice",
    "label": "Voice",
    "provider": "gemini",
    "provider_name": "Gemini",
    "name": "Kore",
    "detail": "Firm",
    "plays_on": "gemini-3.8-flash-tts",
    "price": None,
    "models": ["gemini-3.8-flash-tts"],
    "sample": ["Kore", "gemini-3.8-flash-tts"],
    "use": {"tts_voice": "Kore"},
    "used": False,
    "blocked": None,
}


def test_a_row_is_kept_by_its_kind_provider_and_text() -> None:
    assert tab.kept(KORE, kind="voice", provider="", query="firm")
    assert tab.kept(KORE, kind="", provider="gemini", query="")
    assert not tab.kept(KORE, kind="tts", provider="", query="")
    assert not tab.kept(KORE, kind="", provider="openai", query="")
    assert not tab.kept(KORE, kind="", provider="", query="marin")


def test_a_row_plays_its_own_voice_on_its_own_model() -> None:
    assert tab.preview_url(KORE).endswith(
        "/api/v1/voice/preview/Kore?model=gemini-3.8-flash-tts"
    )
    assert tab.preview_url(KORE | {"sample": None}) is None


async def test_use_puts_the_row_on_the_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[tuple[str, Any]] = []
    overview = {"rows": [KORE], "profiles": [], "active": None, "kinds": {}}

    class Api:
        async def post(self, path: str, json: Any = None) -> Any:
            posted.append((path, json))
            return overview

    voice = tab.VoiceSettingsTab()
    monkeypatch.setattr(voice, "_api", Api)
    monkeypatch.setattr(voice, "_show", lambda found: None)

    await voice._use(KORE)

    assert posted == [("/api/v1/voice/use", {"tts_voice": "Kore"})]


def test_a_row_fills_the_pages_columns() -> None:
    """Kind, provider, name, details, plays on, price, then play and Use:
    the htmx page's columns, the same order."""
    cells = tab.VoiceSettingsTab()._cells(KORE, 0)

    assert [h.header for h in tab.COLUMNS][:6] == [
        "Kind",
        "Provider",
        "Name",
        "Details",
        "Plays on",
        "Price / 1M",
    ]
    assert [cells[0], cells[2], cells[3], cells[4], cells[5]] == [
        "Voice",
        "Kore",
        "Firm",
        "gemini-3.8-flash-tts",
        "",
    ]


def test_the_ai_modal_shows_the_voice_tab() -> None:
    """The modal finds the tab where it lives: a wrong path was swallowed
    as "this stack has no voice", and the tab silently never showed."""
    from app.components.frontend.dashboard.modals import ai_modal

    assert ai_modal.VoiceSettingsTab is tab.VoiceSettingsTab
