"""The inference API (``api/inference.py``): the speech server as it
answers, a line said in one of its voices, and its model unloaded or
reloaded; the hearing server as it answers, and a model of its loaded or
unloaded. Its Overseer page plays and moves through it; the
``inference`` CLI calls the same client. The client is faked here; its own
requests are ``tests/core/test_speech_server.py``'s."""

from fastapi.testclient import TestClient
import pytest

from app.core import hearing_server, speech_server
from tests._audit import as_admin
from tests._fake_ollama import (
    HEARING_READY,
    PARAKEET,
    RUNNING,
    SPEECH_READY,
    hearing,
    serve,
    speaking,
)

API = "/api/v1/inference/speech"
HEARING_API = "/api/v1/inference/hearing"


@pytest.fixture
def speech(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    return speaking(monkeypatch)


@pytest.fixture
def admin(client: TestClient) -> TestClient:
    return as_admin(client)


def test_the_reading_is_the_servers(
    admin: TestClient, speech: list[tuple[str, ...]]
) -> None:
    answer = admin.get(API)

    assert answer.status_code == 200
    assert answer.json()["voices"] == SPEECH_READY.voices


def test_a_line_is_said_as_an_mp3(
    admin: TestClient, speech: list[tuple[str, ...]]
) -> None:
    answer = admin.get(f"{API}/say", params={"voice": "af_heart", "text": "Hi."})

    assert answer.status_code == 200
    assert (answer.headers["content-type"], answer.content) == ("audio/mpeg", b"ID3")
    assert speech == [("say", "Hi.", "af_heart")]


def test_a_voice_played_alone_says_the_sample_line(
    admin: TestClient, speech: list[tuple[str, ...]]
) -> None:
    admin.get(f"{API}/say", params={"voice": "af_heart"})

    assert speech == [("say", speech_server.LINE, "af_heart")]


@pytest.mark.parametrize("action", speech_server.ACTIONS)
def test_the_model_is_moved(
    admin: TestClient, speech: list[tuple[str, ...]], action: str
) -> None:
    assert admin.post(f"{API}/{action}").status_code == 204
    assert speech == [("move", action)]


def test_only_unload_and_reload_are_actions(
    admin: TestClient, speech: list[tuple[str, ...]]
) -> None:
    assert admin.post(f"{API}/delete").status_code == 404
    assert speech == []


def test_a_change_is_an_operators(
    client: TestClient, speech: list[tuple[str, ...]]
) -> None:
    """Unload and reload are an operator's (``get_admin_actor``); this
    client is none: signed out where there is auth, not on loopback where
    there is none."""
    assert client.post(f"{API}/unload").status_code in (401, 403)
    assert speech == []


def test_a_flag_left_off_says_to_turn_it_on(
    admin: TestClient, speech: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refused(url: str, action: str) -> None:
        flag = "ALLOW_DEV_UNLOAD"
        raise speech_server.SpeechServerError(speech_server.left_off([flag]), flag)

    monkeypatch.setattr(speech_server, "move", refused)

    answer = admin.post(f"{API}/unload")

    assert answer.status_code == 409
    assert "ALLOW_DEV_UNLOAD=true" in answer.json()["detail"]


def test_without_a_server_it_says_how_to_set_one(admin: TestClient) -> None:
    answer = admin.get(API)

    assert answer.status_code == 404
    assert "SPEECH_BASE_URL" in answer.json()["detail"]


def test_every_engine_is_in_the_status(
    admin: TestClient, speech: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``GET /inference`` lists every engine, as Overseer's overview does."""
    serve(monkeypatch)

    answer = admin.get("/api/v1/inference")

    assert answer.status_code == 200
    rows = {r["id"]: r for r in answer.json()["engines"]}
    assert set(rows) >= {"ollama", speech_server.SLUG}
    assert rows["ollama"]["loaded"][0]["name"] == RUNNING.name
    assert answer.json()["reported_bytes"] == RUNNING.size_vram


@pytest.fixture
def heard(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    return hearing(monkeypatch)


def test_the_hearing_reading_is_the_servers(
    admin: TestClient, heard: list[tuple[str, ...]]
) -> None:
    answer = admin.get(HEARING_API)

    assert answer.status_code == 200
    assert answer.json()["loaded"] == HEARING_READY.loaded


@pytest.mark.parametrize("action", ["load", "unload"])
def test_a_hearing_model_is_moved(
    admin: TestClient, heard: list[tuple[str, ...]], action: str
) -> None:
    moved = admin.post(f"{HEARING_API}/{action}/{PARAKEET}")

    assert moved.status_code == 204
    assert heard == [("move", action, PARAKEET)]


def test_only_load_and_unload_move_a_hearing_model(
    admin: TestClient, heard: list[tuple[str, ...]]
) -> None:
    assert admin.post(f"{HEARING_API}/pull/{PARAKEET}").status_code == 404
    assert heard == []


def test_moving_a_hearing_model_is_an_operators(
    client: TestClient, heard: list[tuple[str, ...]]
) -> None:
    answer = client.post(f"{HEARING_API}/unload/{PARAKEET}")

    assert answer.status_code in (401, 403)
    assert heard == []


def test_a_move_the_hearing_server_refuses_is_its_fault(
    admin: TestClient, heard: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refused(url: str, action: str, model: str) -> None:
        raise speech_server.SpeechServerError("The hearing server refused (404).")

    monkeypatch.setattr(hearing_server, "move", refused)

    answer = admin.post(f"{HEARING_API}/unload/{PARAKEET}")

    assert answer.status_code == 502


def test_without_a_hearing_server_it_says_how_to_set_one(admin: TestClient) -> None:
    answer = admin.get(HEARING_API)

    assert answer.status_code == 404
    assert "HEARING_BASE_URL" in answer.json()["detail"]
