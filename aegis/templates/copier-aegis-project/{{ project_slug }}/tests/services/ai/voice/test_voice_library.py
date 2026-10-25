"""Gemini's voice library (``library``): its voices beyond the 30 prebuilt
ones, regional accents among them, listed with its key and kept."""

import asyncio
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
    library.LOADING.clear()


def _client(*pages: Any) -> Any:
    """Gemini's voice list, a page at a time (an exception raised instead)."""

    async def voices(page_token: str | None = None, **kwargs: Any) -> Any:
        if isinstance(pages[0], Exception):
            raise pages[0]
        at = int(page_token or 0)
        last = at == len(pages) - 1
        return SimpleNamespace(
            voices=pages[at], next_page_token=None if last else str(at + 1)
        )

    return SimpleNamespace(aio=SimpleNamespace(voices=SimpleNamespace(list=voices)))


BOB = SimpleNamespace(
    id="voice_en_ie_bob", display_name="Bob", gender="MALE",
    accent="Dublin English", description="Easy", persona=None,
)  # fmt: skip


async def test_the_library_is_read_page_by_page_beyond_the_prebuilt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The library runs to thousands of voices over many pages: every page
    is read, the prebuilt 30 left as they are."""
    monkeypatch.setattr(library, "_client", lambda key: _client(FOUND, [BOB]))

    await library.fill("k")

    assert set(library.KEPT) == {"voice_en_gb_amelia", "voice_en_ie_bob"}
    amelia = get_voice("voice_en_gb_amelia")
    assert (amelia.name, amelia.gender, amelia.accent) == (
        "Amelia",
        "female",
        "British",
    )
    assert "gemini-3.8-flash-tts" in amelia.model_ids


async def test_asking_never_waits_on_the_library(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its first answer takes seconds: a page drawing the voices gets what
    is in so far, the library loading behind it, asked for once."""
    asked: list[str] = []
    answered = asyncio.Event()

    def client(key: str) -> Any:
        asked.append(key)

        async def voices(**kwargs: Any) -> Any:
            await answered.wait()
            return SimpleNamespace(voices=[BOB], next_page_token=None)

        return SimpleNamespace(aio=SimpleNamespace(voices=SimpleNamespace(list=voices)))

    monkeypatch.setattr(library, "_client", client)

    first = await asyncio.wait_for(library.gemini_library("k"), 1)
    again = await asyncio.wait_for(library.gemini_library("k"), 1)
    answered.set()
    await asyncio.gather(*library.LOADING)

    assert first == again == [] and asked == ["k"]
    assert "voice_en_ie_bob" in library.KEPT


async def test_a_library_that_cannot_be_read_is_none_and_said(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logged: list[str] = []
    monkeypatch.setattr(library, "_client", lambda key: _client(RuntimeError("no")))
    monkeypatch.setattr(
        library.logger, "exception", lambda said, *a, **k: logged.append(said)
    )

    await library.fill("k")

    assert library.KEPT == {} and len(logged) == 1


async def test_a_library_voice_has_a_tone_and_no_prebuilt_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The library lists the prebuilt 30 again under lowercase ids, and
    gives a persona where a tone would be: its description says the tone."""
    soft = SimpleNamespace(
        id="voice_x", display_name="Narrator 1", gender="FEMALE", accent="Dublin English",
        persona="Storyteller & Narrator",
        description="Soft, calm, and soothing voice with a higher pitch.",
    )
    told = SimpleNamespace(
        id="voice_y", display_name="Lawyer 2", gender="MALE", accent="Egyptian Arabic",
        persona="High-Trust Advisor", description="43-year-old Lawyer. Voice is warm and engaging.",
    )
    kore_again = SimpleNamespace(
        id="kore", display_name="Kore", gender="FEMALE", accent="General American",
        persona=None, description="Firm",
    )  # fmt: skip
    monkeypatch.setattr(library, "_client", lambda key: _client([soft, told, kore_again]))

    await library.fill("k")

    assert set(library.KEPT) == {"voice_x", "voice_y"}
    assert (library.KEPT["voice_x"].tone, library.KEPT["voice_y"].tone) == ("Soft", "Warm")
