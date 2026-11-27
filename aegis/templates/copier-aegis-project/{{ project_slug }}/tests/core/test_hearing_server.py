"""A hearing server you run (``app/core/hearing_server.py``), speaches
first: what it answers about itself, and its models loaded or unloaded.
The server is a stub; the real client's requests are answered in the test."""

import pytest

from app.core import hearing_server, speech_server
from tests._speech_server import PARAKEET, SPEACHES, WHISPER, serving

URL = "http://localhost:8010/v1"


async def test_a_reading_has_its_models_and_those_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = serving(monkeypatch, SPEACHES)

    reading = await hearing_server.read(URL)

    assert reading.available
    assert reading.models == sorted([PARAKEET, WHISPER])
    assert reading.loaded == [PARAKEET]
    # Hearing models only: speaches serves speech and embeddings too.
    [listed] = [r for r in sent if r.url.path == "/v1/models"]
    assert listed.url.params["task"] == "automatic-speech-recognition"


async def test_only_its_hearing_models_count_as_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """speaches holds its voice-activity model in memory beside the one it
    transcribes with; that one is not a hearing model it lists."""
    serving(
        monkeypatch, SPEACHES | {"/api/ps": {"models": [PARAKEET, "silero_vad_v5"]}}
    )

    reading = await hearing_server.read(URL)

    assert reading.loaded == [PARAKEET]


async def test_a_server_without_speaches_own_routes_still_lists_its_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any OpenAI-compatible hearing server: what is in memory goes unsaid."""
    serving(monkeypatch, {"/v1/models": SPEACHES["/v1/models"]})

    reading = await hearing_server.read(URL)

    assert reading.available


async def test_a_server_answering_its_own_page_for_speaches_route_still_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server that answers every path with a web page: what is in memory
    goes unsaid, and its models are still listed."""
    serving(monkeypatch, {"/v1/models": SPEACHES["/v1/models"], "/api/ps": b"<html>"})

    reading = await hearing_server.read(URL)

    assert reading.available and reading.loaded is None
    assert reading.loaded is None


async def test_a_server_down_is_read_as_down(monkeypatch: pytest.MonkeyPatch) -> None:
    serving(monkeypatch, {})

    reading = await hearing_server.read(URL)

    assert not reading.available
    assert reading.error


@pytest.mark.parametrize(("action", "method"), [("load", "POST"), ("unload", "DELETE")])
async def test_a_model_is_loaded_or_unloaded(
    monkeypatch: pytest.MonkeyPatch, action: str, method: str
) -> None:
    sent = serving(monkeypatch, {f"{method} /api/ps/{PARAKEET}": 200})

    await hearing_server.move(URL, action, PARAKEET)

    [request] = sent
    assert (request.method, request.url.path) == (method, f"/api/ps/{PARAKEET}")


async def test_a_move_it_refuses_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    serving(monkeypatch, {})

    with pytest.raises(speech_server.SpeechServerError, match="404"):
        await hearing_server.move(URL, "unload", PARAKEET)
    with pytest.raises(ValueError, match="load or unload"):
        await hearing_server.move(URL, "pull", PARAKEET)


def test_its_figures_say_what_it_holds() -> None:
    reading = hearing_server.HearingServerReading(
        base_url=URL, available=True, models=[PARAKEET, WHISPER], loaded=[PARAKEET]
    )

    assert hearing_server.figures(reading) == [("Models", "2"), ("In memory", "1")]
