"""``inference``: the speech server as it answers, a line said into an MP3,
and its model unloaded or reloaded; the client the inference API and
Overseer > Inference > Speech call, faked here."""

from pathlib import Path

import pytest

from app.core import speech_server
from tests._cli import invoke
from tests._fake_ollama import SPEECH_READY, speaking


def test_speech_says_what_the_server_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    closed = SPEECH_READY.model_copy(
        update={"closed": ["ALLOW_DEV_UNLOAD"], "threads": 12}
    )
    speaking(monkeypatch, closed)

    result = invoke(["inference", "speech"])

    assert result.exit_code == 0
    assert "Voices: 2" in result.output
    assert "Threads: 12" in result.output
    assert "General American, female: af_heart" in result.output
    assert "ALLOW_DEV_UNLOAD=true" in result.output


def test_speak_writes_the_line_into_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    said = speaking(monkeypatch)
    out = tmp_path / "hello.mp3"

    result = invoke(["inference", "speak", "Hi.", "-v", "bm_george", "-o", str(out)])

    assert result.exit_code == 0
    assert out.read_bytes() == b"ID3"
    assert said == [("say", "Hi.", "bm_george")]


@pytest.mark.parametrize("action", speech_server.ACTIONS)
def test_speech_model_moves_it(monkeypatch: pytest.MonkeyPatch, action: str) -> None:
    done = speaking(monkeypatch)

    assert invoke(["inference", "speech-model", action]).exit_code == 0
    assert done == [("move", action)]


def test_without_a_server_it_says_how_to_set_one() -> None:
    result = invoke(["inference", "speech"])

    assert result.exit_code == 1
    assert "SPEECH_BASE_URL" in result.output
