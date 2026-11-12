"""What the catalog lists for the voice that runs in the app's own process:
Kokoro speaking (``tts/kokoro.py``) and Parakeet hearing
(``stt/parakeet.py``). Kept out of ``catalog`` for its size; it adds these
to its lists. Also how either loads its model (``loaded_once``)."""

from collections.abc import Callable
from functools import cache
import threading
from typing import Any

from .models import (
    DEFAULT_STT_MODELS,
    DEFAULT_TTS_MODELS,
    ModelInfo,
    ProviderInfo,
    STTProvider,
    TTSProvider,
    VoiceInfo,
)

_IN_APP = "runs in the app on the CPU, no key"


def loaded_once(load: Callable[..., Any]) -> Callable[..., Any]:
    """``load`` run once per argument for the whole process, however many
    threads ask at once: a model is seconds and hundreds of MB to load,
    and the meetings bot hears several speakers together."""
    loaded = cache(load)
    lock = threading.Lock()

    def model(*args: str) -> Any:
        with lock:  # ponytail: per loader, so two models of one load in turn
            return loaded(*args)

    return model


TTS_PROVIDER = ProviderInfo(
    id=TTSProvider.KOKORO.value,
    name="Kokoro",
    type="tts",
    requires_api_key=False,
    is_local=True,
    description=f"Kokoro-82M: {_IN_APP}",
)
STT_PROVIDER = ProviderInfo(
    id=STTProvider.PARAKEET.value,
    name="Parakeet",
    type="stt",
    requires_api_key=False,
    is_local=True,
    description=f"NVIDIA Parakeet v3, 25 languages: {_IN_APP}",
)

TTS_MODELS = [
    ModelInfo(
        id=DEFAULT_TTS_MODELS[TTSProvider.KOKORO],
        name="Kokoro v1.0",
        provider_id=TTSProvider.KOKORO.value,
        description="int8, about 120MB, fetched on first use",
        supports_streaming=False,
        speeds=(0.5, 2.0),
    )
]
STT_MODELS = [
    ModelInfo(
        id=DEFAULT_STT_MODELS[STTProvider.PARAKEET],
        name="Parakeet TDT 0.6B v3",
        provider_id=STTProvider.PARAKEET.value,
        description="int8, about 670MB, fetched from Hugging Face on first use",
        supports_streaming=False,
    )
]

# Kokoro v1.0's English voices. The prefix is the accent (a: American, b:
# British) and the gender (f, m); Kokoro names no tone. Each is named by
# its id: half share a name with an OpenAI or Gemini voice (af_alloy,
# af_kore), and a second "Alloy" would read as the same one.
_ACCENTS = {"a": "General American", "b": "British"}
_GENDERS = {"f": "female", "m": "male"}
_KOKORO_VOICES = (
    "af_heart af_alloy af_aoede af_bella af_jessica af_kore af_nicole af_nova "
    "af_river af_sarah af_sky am_adam am_echo am_eric am_fenrir am_liam "
    "am_michael am_onyx am_puck am_santa bf_alice bf_emma bf_isabella bf_lily "
    "bm_daniel bm_fable bm_george bm_lewis"
).split()

VOICES = [
    VoiceInfo(
        id=voice,
        name=voice,
        provider_id=TTSProvider.KOKORO.value,
        model_ids=[m.id for m in TTS_MODELS],
        description=f"Kokoro, {_ACCENTS[voice[0]]} {_GENDERS[voice[1]]}",
        gender=_GENDERS[voice[1]],
        accent=_ACCENTS[voice[0]],
    )
    for voice in _KOKORO_VOICES
]
