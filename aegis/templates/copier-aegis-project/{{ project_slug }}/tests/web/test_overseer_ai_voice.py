"""The Overseer AI page's Voice section: what speaks and what listens (from
settings, with each provider's key state), every voice of the speaking
provider with a play button, a sentence spoken in a chosen voice, and an
audio file transcribed. Playback rides the voice API's preview route;
transcription is the speech API's own function."""

from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

pytest.importorskip("app.services.ai.domains.voice", reason="no voice in this stack")

from app.components.web_frontend import overseer_ai_voice  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services.system.models import ComponentStatus  # noqa: E402
from tests.web.dom import one, select, text, triggers  # noqa: E402
from tests.web.overseer import sign_in, status_with  # noqa: E402

PAGE = "/overseer/services/ai"
PARTIALS = "/partials/overseer/ai"


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    ai = ComponentStatus(name="ai", message="AI", metadata={"engine": "pydantic-ai"})
    sign_in(app, monkeypatch, status_with(services=[ai]))
    return TestClient(app)


def _voice(client: TestClient) -> str:
    response = client.get(f"{PAGE}/voice")
    assert response.status_code == 200, response.text
    return response.text


def test_speaking_and_listening_say_what_they_need(client: TestClient) -> None:
    html = _voice(client)
    speaking = text(one(html, "#ai-voice-speaking"))
    assert "OpenAI" in speaking and "tts-1" in speaking
    assert "OPENAI_API_KEY" in speaking  # named, since it is missing
    assert "whisper-1" in text(one(html, "#ai-voice-listening"))


def test_each_voice_plays_from_the_preview_route(client: TestClient) -> None:
    html = _voice(client)
    rows = select(html, "#ai-voices tbody tr")
    assert rows
    audio = one(rows[0], "audio")
    assert audio.get("src").startswith("/api/v1/voice/preview/")
    assert audio.get("preload") == "none"


def test_a_sentence_is_spoken_in_a_chosen_voice(client: TestClient) -> None:
    form = one(_voice(client), "#ai-voice-try")
    assert (
        one(form, "[data-preview-base]").get("data-preview-base")
        == "/api/v1/voice/preview/"
    )
    assert select(form, "select[name=voice] option")


def test_an_upload_is_transcribed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def transcribe(audio: Any) -> Any:
        return SimpleNamespace(text="hello from the file", language="en", duration=1.2)

    monkeypatch.setattr(overseer_ai_voice, "transcribe", transcribe)
    response = client.post(
        f"{PARTIALS}/voice/transcribe",
        files={"audio": ("clip.wav", b"RIFF....", "audio/wav")},
    )
    assert response.status_code == 200, response.text
    assert "hello from the file" in text(one(response.text, "#ai-voice-transcript"))


def test_a_refused_upload_is_the_toast(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    async def transcribe(audio: Any) -> Any:
        raise HTTPException(status_code=400, detail="Unsupported audio format: txt")

    monkeypatch.setattr(overseer_ai_voice, "transcribe", transcribe)
    response = client.post(
        f"{PARTIALS}/voice/transcribe",
        files={"audio": ("notes.txt", b"hi", "text/plain")},
    )
    toast = triggers(response)["toast"]
    assert toast["tone"] == "error" and "Unsupported audio format" in toast["text"]
