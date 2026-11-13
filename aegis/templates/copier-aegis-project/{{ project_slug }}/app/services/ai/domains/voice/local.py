"""What the catalog lists for the voice that runs in the app's own process:
Kokoro speaking (``tts/kokoro.py``) and Parakeet hearing
(``stt/parakeet.py``). Kept out of ``catalog`` for its size; it adds these
to its lists. Also how either loads its model (``loaded_once``)."""

from collections.abc import Callable
from functools import cache
import threading
from typing import Any

from app.core import speech_server

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

# Kokoro v1.0's English voices, the ones the app speaks in-process. The
# prefix is the language or accent and the gender (``speech_server.traits``);
# Kokoro names no tone. Each is named by its id: half share a name with an
# OpenAI or Gemini voice (af_alloy, af_kore), and a second "Alloy" would read
# as the same one.
KOKORO_VOICES = tuple(
    (
        "af_heart af_alloy af_aoede af_bella af_jessica af_kore af_nicole af_nova "
        "af_river af_sarah af_sky am_adam am_echo am_eric am_fenrir am_liam "
        "am_michael am_onyx am_puck am_santa bf_alice bf_emma bf_isabella bf_lily "
        "bm_daniel bm_fable bm_george bm_lewis"
    ).split()
)


def kokoro_voice(
    name: str, provider: str, models: list[str], id: str = ""
) -> VoiceInfo:
    """One of Kokoro's voices as the catalog lists it, its accent and gender
    read off its name (``bf_``: British, female); a name past that (a mix a
    server saved) is listed as it is."""
    accent, gender = speech_server.traits(name) or (None, None)
    return VoiceInfo(
        id=id or name,
        name=name,
        provider_id=provider,
        model_ids=models,
        description=f"Kokoro, {accent} {gender}" if accent else "Kokoro",
        gender=gender,
        accent=accent,
    )


VOICES = [
    kokoro_voice(voice, TTSProvider.KOKORO.value, [m.id for m in TTS_MODELS])
    for voice in KOKORO_VOICES
]
