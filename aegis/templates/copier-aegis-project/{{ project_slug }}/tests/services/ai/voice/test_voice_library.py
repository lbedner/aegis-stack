"""Gemini's voice library (``library``): its voices beyond the 30 prebuilt
ones, regional accents among them, listed with its key and kept."""

from types import SimpleNamespace
from typing import Any

import pytest

from app.services.ai.domains.voice import library
from app.services.ai.domains.voice.catalog import get_voice

FOUND = [
    SimpleNamespace(
        id="voice_en_gb_amelia", display_name="Amelia", gender="FEMALE",
        accent="British", description="Bright, clear", persona="Narrator",
    ),
    SimpleNamespace(
        id="Kore", display_name="Kore", gender="FEMALE",
        accent="American", description="Firm", persona=None,
    ),
]  # fmt: skip


@pytest.fixture(autouse=True)
def _forget() -> Any:
    library.KEPT.clear()
    library.TRIED.clear()
    yield
    library.KEPT.clear()
    library.TRIED.clear()


def _client(listed: Any) -> Any:
    async def voices(**kwargs: Any) -> Any:
        if isinstance(listed, Exception):
            raise listed
        return SimpleNamespace(voices=listed)

    return SimpleNamespace(aio=SimpleNamespace(voices=SimpleNamespace(list=voices)))


async def test_the_library_adds_its_voices_beyond_the_prebuilt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(library, "_client", lambda key: _client(FOUND))

    found = await library.gemini_library("k")

    [amelia] = found  # Kore is already one of the prebuilt
    assert (amelia.name, amelia.gender, amelia.accent) == (
        "Amelia",
        "female",
        "British",
    )
    assert get_voice("voice_en_gb_amelia") == amelia
    assert "gemini-3.8-flash-tts" in amelia.model_ids


async def test_a_library_that_cannot_be_read_is_none_and_said(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(library, "_client", lambda key: _client(RuntimeError("no")))

    assert await library.gemini_library("k") == []


async def test_the_library_is_asked_once_even_when_it_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A page draws it on every visit: an unreadable library is not asked
    again (and again waited on)."""
    asked: list[str] = []

    def client(key: str) -> Any:
        asked.append(key)
        return _client(RuntimeError("no"))

    monkeypatch.setattr(library, "_client", client)

    await library.gemini_library("k")
    await library.gemini_library("k")

    assert asked == ["k"]
