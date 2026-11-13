"""A speech server you run (``app/core/speech_server.py``): where this
process reaches it, and what it answers. The server is a stub; the real
client's requests are answered in the test."""

from typing import Any

import httpx
import pytest

from app.core import speech_server
from app.core.config import Settings
from tests._fake_dns import answering

URL = "http://localhost:8880/v1"
MODELS = {"object": "list", "data": [{"id": "tts-1"}, {"id": "kokoro"}]}
VOICES = {"voices": [{"id": "bm_george"}, "af_heart"]}
# What Kokoro-FastAPI reports of itself at its root, past OpenAI's API.
KOKORO_FASTAPI = {
    "/web/config": {"version": "0.10.1", "tuner": False},
    "/dev/model": {
        "backend": "kokoro_v1",
        "device": "mps",
        "loaded": True,
        "active_requests": 1,
        "idle_seconds": 4.5,
        "seconds_until_auto_unload": None,
    },
    "/debug/threads": {"total_threads": 12, "memory_mb": 812.5},
}


def _serving(
    monkeypatch: pytest.MonkeyPatch, answers: dict[str, Any]
) -> list[httpx.Request]:
    """A server answering each path from ``answers`` (a body, or a status
    code alone), 404 past them. Returns the requests that reached it."""
    sent: list[httpx.Request] = []
    real = httpx.AsyncClient

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        found = answers.get(request.url.path, 404)
        if isinstance(found, int):
            return httpx.Response(found)
        if isinstance(found, bytes):
            return httpx.Response(200, content=found)
        return httpx.Response(200, json=found)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(answer), **kw),
    )
    return sent


LISTING = {"/v1/models": MODELS, "/v1/audio/voices": VOICES}


async def test_a_reading_has_its_models_and_voices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serving(monkeypatch, LISTING)

    reading = await speech_server.read(URL)

    assert reading.available
    assert (reading.models, reading.voices) == (
        ["kokoro", "tts-1"],
        ["af_heart", "bm_george"],
    )
    # A server with OpenAI's API alone reports nothing of itself.
    assert (reading.version, reading.loaded, reading.memory_bytes) == (None,) * 3
    assert reading.closed == []


async def test_kokoro_fastapi_reports_its_model_and_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serving(monkeypatch, LISTING | KOKORO_FASTAPI)

    reading = await speech_server.read(URL)

    assert (reading.version, reading.device, reading.loaded) == ("0.10.1", "mps", True)
    assert (reading.active_requests, reading.idle_seconds) == (1, 4.5)
    assert (reading.memory_bytes, reading.threads) == (812.5 * 2**20, 12)
    assert dict(speech_server.facts(reading))["Idle for"] == "4s"


async def test_a_flag_left_off_names_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kokoro-FastAPI refuses (403) what its flags keep closed: the reading
    names the flag that opens it."""
    closed = {"/dev/model": 403, "/debug/threads": 403}
    _serving(monkeypatch, LISTING | KOKORO_FASTAPI | closed)

    reading = await speech_server.read(URL)

    assert reading.version == "0.10.1"
    assert reading.loaded is None
    assert reading.closed == ["ALLOW_DEV_UNLOAD", "ENABLE_DEBUG_ENDPOINTS"]


async def test_a_line_is_said_and_its_time_charted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import series

    sent = _serving(monkeypatch, {"/v1/audio/speech": b"ID3 audio"})
    charted: list[dict[str, float]] = []

    async def record(values: dict[str, float]) -> None:
        charted.append(values)

    monkeypatch.setattr(series, "record", record)

    audio = await speech_server.say(URL, "Hello there.", "af_heart")

    assert audio == b"ID3 audio"
    asked = sent[0].read()
    assert b'"voice":"af_heart"' in asked and b'"input":"Hello there."' in asked
    assert list(charted[0]) == [speech_server.LATENCY["file"]]


@pytest.mark.parametrize("action", speech_server.ACTIONS)
async def test_the_model_is_moved_at_the_server_root(
    monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    sent = _serving(monkeypatch, {f"/dev/{action}": {"status": action}})

    await speech_server.move(URL, action)

    assert (sent[0].method, sent[0].url.path) == ("POST", f"/dev/{action}")


async def test_a_refusal_names_a_flag_only_where_one_is_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only its dev routes are behind ALLOW_DEV_UNLOAD: a 403 to a line is
    the server's own refusal, and names no flag."""
    _serving(monkeypatch, {"/dev/unload": 403, "/v1/audio/speech": 403})

    with pytest.raises(speech_server.SpeechServerError) as moved:
        await speech_server.move(URL, "unload")
    with pytest.raises(speech_server.SpeechServerError) as said:
        await speech_server.say(URL, "Hi.", "af_heart")

    assert moved.value.flag == "ALLOW_DEV_UNLOAD"
    assert "ALLOW_DEV_UNLOAD=true" in str(moved.value)
    assert said.value.flag is None
    assert "ALLOW_DEV_UNLOAD" not in str(said.value)


def test_openais_names_read_as_aliases_of_the_servers_own() -> None:
    """Kokoro-FastAPI answers to OpenAI's model names too, for OpenAI's
    clients; they are not models it runs. A server with no model of its
    own runs what it lists."""

    def facts(*models: str) -> dict[str, str]:
        reading = speech_server.SpeechServerReading(
            base_url=URL, available=True, models=list(models)
        )
        return dict(speech_server.facts(reading))

    found = facts("gpt-4o-mini-tts", "kokoro", "tts-1", "tts-1-hd")
    assert found["Models"] == "kokoro"
    assert found["Aliases"] == "gpt-4o-mini-tts, tts-1, tts-1-hd"
    alone = facts("tts-1")
    assert alone["Models"] == "tts-1" and "Aliases" not in alone


def test_voices_are_grouped_by_accent_and_gender() -> None:
    found = speech_server.grouped(["bf_emma", "af_heart", "am_adam", "af_bella", "x"])

    assert found == [
        ("British, female", ["bf_emma"]),
        ("General American, female", ["af_heart", "af_bella"]),
        ("General American, male", ["am_adam"]),
        ("Other", ["x"]),
    ]


@pytest.mark.parametrize("answer", [httpx.Response(503), httpx.Response(200)])
async def test_a_server_that_cannot_be_read_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, answer: httpx.Response
) -> None:
    answering(monkeypatch, answer)

    reading = await speech_server.read(URL)

    assert (reading.available, reading.base_url) == (False, URL)
    assert reading.error


class _Shell:
    """Settings as a shell on the host has them, with only the speech
    settings given: this ships to every stack, and only inference and
    ai[voice] carry them."""

    is_docker = False
    localhost_url = staticmethod(Settings.localhost_url)

    def __init__(self, **given: Any) -> None:
        self.__dict__.update(given)


def test_a_shell_on_the_host_reaches_a_docker_name_on_localhost() -> None:
    for name in ("host.docker.internal", "kokoro-fastapi"):
        assert (
            speech_server.reach(_Shell(SPEECH_BASE_URL=f"http://{name}:8880/v1")) == URL
        )
    assert speech_server.reach(_Shell()) is None


def test_a_shell_takes_the_port_make_serve_published_it_on() -> None:
    published = _Shell(
        SPEECH_BASE_URL="http://kokoro-fastapi:8880/v1", SPEECH_HOST_PORT=8890
    )

    assert speech_server.reach(published) == "http://localhost:8890/v1"


def test_the_app_in_docker_reaches_it_by_its_own_name() -> None:
    named = "http://kokoro-fastapi:8880/v1"

    assert speech_server.reach(_Shell(is_docker=True, SPEECH_BASE_URL=named)) == named
