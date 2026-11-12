"""Speaking (Kokoro) and hearing (Parakeet) in the app's own process: no
server, no key, opt-in packages. The models are stubbed: their files are
fetched on first use, never in a test."""

from pathlib import Path
import re
import threading
from typing import Any

import pytest

from app.services.ai.domains.voice import get_voice, local
from app.services.ai.domains.voice.models import (
    AudioFormat,
    AudioInput,
    SpeechRequest,
    STTProvider,
    TTSProvider,
)
from app.services.ai.domains.voice.stt import STTConfig, get_stt_provider, parakeet
from app.services.ai.domains.voice.tts import TTSConfig, get_tts_provider, kokoro
from tests._voice_packages import packages_installed


class _Kokoro:
    def __init__(self) -> None:
        self.asked: dict[str, Any] = {}

    def create(self, text: str, **asked: Any) -> tuple[list[float], int]:
        self.asked = {"text": text, **asked}
        return [0.0], 24_000


async def test_kokoro_speaks_a_wav_in_the_voices_accent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packages_installed(monkeypatch, True)
    said = get_tts_provider(TTSProvider.KOKORO)
    assert isinstance(said, kokoro.KokoroProvider)
    stub = _Kokoro()
    monkeypatch.setattr(kokoro, "model", lambda: stub)
    monkeypatch.setattr(kokoro, "pcm16", lambda samples: b"\x00\x00" * 24_000)

    result = await said.synthesize(SpeechRequest(text="Hello", voice="bm_george"))

    assert stub.asked == {
        "text": "Hello",
        "voice": "bm_george",
        "speed": 1.0,
        "lang": "en-gb",
    }
    assert (result.format, result.duration_seconds) == (AudioFormat.WAV, 1.0)


def test_a_model_file_already_fetched_is_not_fetched_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(kokoro, "CACHE", tmp_path)
    (tmp_path / "voices-v1.0.bin").write_bytes(b"kept")

    assert kokoro.fetched("voices-v1.0.bin").read_bytes() == b"kept"


async def test_parakeet_hears_what_was_said(monkeypatch: pytest.MonkeyPatch) -> None:
    packages_installed(monkeypatch, True)
    heard = get_stt_provider(STTProvider.PARAKEET)
    assert isinstance(heard, parakeet.ParakeetProvider)
    asr = type("Asr", (), {"recognize": lambda self, s, **kw: " Hi there "})()
    monkeypatch.setattr(parakeet, "model", lambda name: asr)
    monkeypatch.setattr(parakeet, "decoded", lambda content: [0.0] * 32_000)

    result = await heard.transcribe(
        AudioInput(content=b"webm", format=AudioFormat.WEBM)
    )

    assert (result.text, result.duration_seconds) == ("Hi there", 2.0)


async def test_not_installed_each_says_how_to_install_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In the settings, and at the first call for whatever reaches the
    providers without them (a saved profile, the meetings bot)."""
    packages_installed(monkeypatch, False)
    said = "kokoro is not installed: uv add kokoro-onnx"
    heard = 'parakeet is not installed: uv add "onnx-asr[cpu,hub]" av'

    tts = await TTSConfig(provider=TTSProvider.KOKORO).validation_errors(None)
    stt = await STTConfig(provider=STTProvider.PARAKEET).validation_errors(None)

    assert (tts, stt) == ([said], [heard])
    with pytest.raises(RuntimeError, match=re.escape(said)):
        get_tts_provider(TTSProvider.KOKORO)
    with pytest.raises(RuntimeError, match=re.escape(heard)):
        get_stt_provider(STTProvider.PARAKEET)


def test_a_model_is_loaded_once_however_many_ask_at_once() -> None:
    """Seconds and hundreds of MB each: the meetings bot hears several
    speakers together, and each must not load its own."""
    loads: list[str] = []
    gate = threading.Event()

    def load(name: str) -> str:
        gate.wait(1)
        loads.append(name)
        return name.upper()

    model = local.loaded_once(load)
    threads = [threading.Thread(target=model, args=("tdt",)) for _ in range(4)]
    for thread in threads:
        thread.start()
    gate.set()
    for thread in threads:
        thread.join()

    assert (loads, model("tdt")) == (["tdt"], "TDT")


def test_kokoros_voices_are_listed_by_their_own_ids() -> None:
    george = get_voice("bm_george")

    assert george is not None and george.provider_id == TTSProvider.KOKORO
    assert (george.gender, george.accent) == ("male", "British")
