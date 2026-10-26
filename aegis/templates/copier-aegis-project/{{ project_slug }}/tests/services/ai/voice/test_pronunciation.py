"""One pronunciation list for every voice (``spoken``): the stack's own
names by default, an app's own registered beside them, and the rows saved
in the Voices dialog over both. Read aloud, a term is swapped as a whole
word; on a live call, the list goes into the model's instructions."""

from collections.abc import Iterator

import pytest

from app.services.ai.domains.voice import spoken
from app.services.ai.domains.voice.models import SpeechRequest
from app.services.ai.domains.voice.spoken import Pronunciation
from app.services.ai.domains.voice.tts import TTSService


@pytest.fixture(autouse=True)
def _fresh_list(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each test starts from the defaults alone."""
    monkeypatch.setattr(spoken, "_registered", {})
    monkeypatch.setattr(spoken, "_saved", {})
    yield


def test_a_term_is_said_as_written_whole_word_any_case() -> None:
    said = spoken.pronounced("TRAEFIK routes to Redis; Traefiker is not a term.")

    assert said == "traffic routes to red-iss; Traefiker is not a term."


def test_a_spelling_the_case_rule_cannot_fold_is_left_as_written() -> None:
    """A dotted capital I matches "SQLite" ignoring case, but lowercases to
    two characters: the text is spoken as written, never a failed answer."""
    assert spoken.pronounced("SQLİTE") == "SQLİTE"


def test_a_term_with_marks_in_it_is_still_a_whole_word() -> None:
    spoken.register_pronunciation("C++", "see plus plus")

    assert spoken.pronounced("Written in C++, not C++x.") == (
        "Written in see plus plus, not C++x."
    )


def test_an_apps_own_term_joins_the_list_and_may_not_claim_one_twice() -> None:
    spoken.register_pronunciation("Steward", "stew-ward")

    with pytest.raises(ValueError, match="Steward"):
        spoken.register_pronunciation("steward", "stoo-erd")
    assert spoken.pronounced("Steward") == "stew-ward"


def test_a_saved_row_wins_over_the_default_and_adds_its_own() -> None:
    spoken.use_saved(
        [
            Pronunciation(term="redis", say="ree-dis"),
            Pronunciation(term="Illiana", say="ill-ee-ah-na", ipa="ɪliˈɑːnə"),
        ]
    )

    found = {p.term.lower(): p for p in spoken.pronunciation_list()}

    assert found["redis"].say == "ree-dis"
    assert found["illiana"].ipa == "ɪliˈɑːnə"
    assert found["traefik"].say == "traffic"
    assert spoken.pronounced("Redis and Illiana") == "ree-dis and ill-ee-ah-na"


def test_a_call_is_told_the_list() -> None:
    told = spoken.pronunciation_instructions()

    assert told.startswith("Pronunciation")
    assert 'Say "Traefik" as "traffic".' in told


def test_every_voice_says_the_list() -> None:
    """Read aloud, the meeting bot, a preview: each reaches the speech
    service, which says the text the list's way."""
    asked = TTSService()._configured(SpeechRequest(text="Behind Traefik."))

    assert asked.text == "Behind traffic."
