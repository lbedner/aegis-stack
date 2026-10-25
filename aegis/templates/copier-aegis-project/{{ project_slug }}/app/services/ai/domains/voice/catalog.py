"""
Voice Catalog Module

Provides in-memory catalog of voice providers, models, and voices
for TTS and STT services. This is static configuration data that
doesn't require database storage.
"""

from typing import Any

from .models import (
    DEFAULT_TTS_MODELS,
    INSTRUCTED_TTS_MODELS,
    REALTIME_TTS_MODELS,
    STT_KEYS,
    TTS_KEYS,
    ModelInfo,
    OpenAIVoice,
    ProviderInfo,
    STTProvider,
    TTSProvider,
    VoiceInfo,
)
from .stt.config import STTConfig
from .tts import realtime
from .tts.config import TTSConfig

# =============================================================================
# TTS Catalog Data
# =============================================================================

_TTS_PROVIDERS: list[ProviderInfo] = [
    ProviderInfo(
        id=TTSProvider.OPENAI.value,
        name="OpenAI",
        type="tts",
        requires_api_key=True,
        api_key_env_var=TTS_KEYS[TTSProvider.OPENAI],
        is_local=False,
        description="OpenAI Text-to-Speech API with natural-sounding voices",
    ),
    ProviderInfo(
        id=TTSProvider.GEMINI.value,
        name="Gemini",
        type="tts",
        requires_api_key=True,
        api_key_env_var=TTS_KEYS[TTSProvider.GEMINI],
        is_local=False,
        description="Gemini's speech models, in the voices Gemini Live speaks",
    ),
]

# OpenAI's speech models: gpt-realtime-2.1-mini (REALTIME_TTS_MODELS) is
# the one going forward. Every /v1/audio/speech model shuts down on Jan 6,
# 2027: gpt-4o-mini-tts (INSTRUCTED_TTS_MODELS) takes delivery
# instructions and every voice; tts-1 and tts-1-hd take neither and know
# only nine of the voices.
_TTS_1 = ["tts-1", "tts-1-hd"]
_SHUTS_DOWN = "Jan 6, 2027"
# The voices the Realtime API does not speak (its SDK lists the rest).
_NOT_REALTIME = frozenset({OpenAIVoice.FABLE, OpenAIVoice.NOVA, OpenAIVoice.ONYX})
# What each provider's delivery instructions steer, as its docs list them.
# Gemini's 3.8 models take style but leave the accent to the voice.
OPENAI_STEERS = [
    "accent",
    "emotion",
    "intonation",
    "impressions",
    "speed",
    "tone",
    "whispering",
]
GEMINI_STEERS = ["style", "tone", "emotion", "pace"]

_TTS_MODELS: list[ModelInfo] = [
    # OpenAI Models
    *(
        ModelInfo(
            id=model,
            name=model,
            provider_id=TTSProvider.OPENAI.value,
            description="Reads the line over the Realtime API; follows "
            "delivery instructions; ten of the voices",
            steers=OPENAI_STEERS,
            speeds=(realtime.SPEED_MIN, realtime.SPEED_MAX),
        )
        for model in REALTIME_TTS_MODELS
    ),
    *(
        ModelInfo(
            id=model,
            name=model,
            provider_id=TTSProvider.OPENAI.value,
            description=note,
            retires=_SHUTS_DOWN,
            supports_streaming=True,
            max_input_chars=4096,
            steers=OPENAI_STEERS,
        )
        for model, note in zip(
            INSTRUCTED_TTS_MODELS,
            (
                "latest build; every voice; follows delivery instructions",
                "pinned March 2025 build; the more expressive one",
                "pinned December 2025 build",
            ),
            strict=True,
        )
    ),
    ModelInfo(
        id="tts-1",
        name="TTS-1",
        provider_id=TTSProvider.OPENAI.value,
        quality="standard",
        description="Fast; nine voices; ignores delivery instructions",
        retires=_SHUTS_DOWN,
        supports_streaming=True,
        max_input_chars=4096,  # OpenAI TTS limit
    ),
    ModelInfo(
        id="tts-1-hd",
        name="TTS-1 HD",
        provider_id=TTSProvider.OPENAI.value,
        quality="hd",
        description="Higher quality; nine voices; ignores delivery instructions",
        retires=_SHUTS_DOWN,
        supports_streaming=True,
        max_input_chars=4096,  # OpenAI TTS limit
    ),
    # Gemini: every voice on both; delivery is the line's speech_metadata style.
    *(
        ModelInfo(
            id=model,
            name=model,
            provider_id=TTSProvider.GEMINI.value,
            quality=quality,
            description=f"{note}; style through instructions, accent from the voice",
            steers=GEMINI_STEERS,
            speeds=None,  # no speed to set
        )
        for model, quality, note in (
            ("gemini-3.8-flash-tts", "hd", "Flagship, studio-grade fidelity"),
            ("gemini-3.8-flash-lite-tts", "standard", "Fast and low cost"),
        )
    ),
]


# OpenAI's voices: who each sounds like (gender, tone, a line about it)
# and whether tts-1 knows it. Marin and cedar, the recommended two, lead.
_OPENAI_VOICES = [
    (OpenAIVoice.MARIN, "female", "Warm", "OpenAI's recommended voice, natural", False),
    (OpenAIVoice.CEDAR, "male", "Calm", "OpenAI's recommended voice, grounded", False),
    (OpenAIVoice.ALLOY, "neutral", "Even", "Neutral, balanced voice", True),
    (OpenAIVoice.ASH, "male", "Clear", "Clear, confident voice", True),
    (OpenAIVoice.BALLAD, "male", "Soft", "Soft, melodic voice", False),
    (OpenAIVoice.CORAL, "female", "Bright", "Bright, friendly voice", True),
    (OpenAIVoice.ECHO, "male", "Warm", "Warm, friendly voice", True),
    (OpenAIVoice.FABLE, "male", "Expressive", "British-accented, narrative voice", True),
    (OpenAIVoice.NOVA, "female", "Upbeat", "Energetic, youthful voice", True),
    (OpenAIVoice.ONYX, "male", "Firm", "Deep, authoritative voice", True),
    (OpenAIVoice.SAGE, "female", "Calm", "Calm, thoughtful voice", True),
    (OpenAIVoice.SHIMMER, "female", "Clear", "Clear, expressive voice", True),
    (OpenAIVoice.VERSE, "male", "Expressive", "Expressive, dynamic voice", False),
]  # fmt: skip

# The one list of voices: the voice API lists it, and a voice profile and
# the voice designer pick from it.
_TTS_VOICES: list[VoiceInfo] = [
    VoiceInfo(
        id=voice.value,
        name=voice.value.title(),
        provider_id=TTSProvider.OPENAI.value,
        model_ids=(REALTIME_TTS_MODELS if voice not in _NOT_REALTIME else [])
        + INSTRUCTED_TTS_MODELS
        + (_TTS_1 if tts_1 else []),
        description=description,
        gender=gender,
        tone=tone,
        accent="British" if voice == OpenAIVoice.FABLE else "American",
    )
    for voice, gender, tone, description, tts_1 in _OPENAI_VOICES
]

# Gemini's prebuilt voices, who each sounds like and the tone Google gives
# it; the same names Gemini Live speaks in.
_GEMINI_VOICES = {
    "Zephyr": ("female", "Bright"), "Puck": ("male", "Upbeat"),
    "Charon": ("male", "Informative"), "Kore": ("female", "Firm"),
    "Fenrir": ("male", "Excitable"), "Leda": ("female", "Youthful"),
    "Orus": ("male", "Firm"), "Aoede": ("female", "Breezy"),
    "Callirrhoe": ("female", "Easy-going"), "Autonoe": ("female", "Bright"),
    "Enceladus": ("male", "Breathy"), "Iapetus": ("male", "Clear"),
    "Umbriel": ("male", "Easy-going"), "Algieba": ("male", "Smooth"),
    "Despina": ("female", "Smooth"), "Erinome": ("female", "Clear"),
    "Algenib": ("male", "Gravelly"), "Rasalgethi": ("male", "Informative"),
    "Laomedeia": ("female", "Upbeat"), "Achernar": ("female", "Soft"),
    "Alnilam": ("male", "Firm"), "Schedar": ("male", "Even"),
    "Gacrux": ("female", "Mature"), "Pulcherrima": ("female", "Forward"),
    "Achird": ("male", "Friendly"), "Zubenelgenubi": ("male", "Casual"),
    "Vindemiatrix": ("female", "Gentle"), "Sadachbia": ("male", "Lively"),
    "Sadaltager": ("male", "Knowledgeable"), "Sulafat": ("female", "Warm"),
}  # fmt: skip
# The 30 Gemini Live speaks too; its library's others only its speech
# models do (``library``).
GEMINI_PREBUILT = frozenset(_GEMINI_VOICES)


def gemini_models() -> list[str]:
    """Gemini's speech models: every one speaks every Gemini voice."""
    return [m.id for m in _TTS_MODELS if m.provider_id == TTSProvider.GEMINI]


_TTS_VOICES += [
    VoiceInfo(
        id=name,
        name=name,
        provider_id=TTSProvider.GEMINI.value,
        model_ids=gemini_models(),
        description=tone,
        gender=gender,
        tone=tone,
    )
    for name, (gender, tone) in _GEMINI_VOICES.items()
]

# Each voice and speech model by id, for the lookups a page makes per row.
_VOICES_BY_ID = {v.id: v for v in _TTS_VOICES}
_MODELS_BY_ID = {m.id: m for m in _TTS_MODELS}

# =============================================================================
# STT Catalog Data
# =============================================================================

_STT_PROVIDERS: list[ProviderInfo] = [
    ProviderInfo(
        id=STTProvider.OPENAI_WHISPER.value,
        name="OpenAI Whisper",
        type="stt",
        requires_api_key=True,
        api_key_env_var=STT_KEYS[STTProvider.OPENAI_WHISPER],
        is_local=False,
        description="OpenAI Whisper API for accurate transcription",
    ),
    ProviderInfo(
        id=STTProvider.GROQ_WHISPER.value,
        name="Groq Whisper",
        type="stt",
        requires_api_key=True,
        api_key_env_var=STT_KEYS[STTProvider.GROQ_WHISPER],
        is_local=False,
        description="Ultra-fast Whisper inference via Groq",
    ),
    ProviderInfo(
        id=STTProvider.FASTER_WHISPER.value,
        name="Faster Whisper",
        type="stt",
        requires_api_key=False,
        api_key_env_var=None,
        is_local=True,
        description="Optimized local Whisper using CTranslate2",
    ),
    ProviderInfo(
        id=STTProvider.WHISPER_LOCAL.value,
        name="Whisper (Local)",
        type="stt",
        requires_api_key=False,
        api_key_env_var=None,
        is_local=True,
        description="Local Whisper via HuggingFace Transformers",
    ),
]

_STT_MODELS: list[ModelInfo] = [
    # OpenAI's transcription models then Whisper
    *(
        ModelInfo(
            id=model,
            name=model,
            provider_id=STTProvider.OPENAI_WHISPER.value,
            description="OpenAI transcription model",
        )
        for model in ("gpt-transcribe", "gpt-4o-transcribe", "gpt-4o-mini-transcribe")
    ),
    ModelInfo(
        id="whisper-1",
        name="Whisper-1",
        provider_id=STTProvider.OPENAI_WHISPER.value,
        quality="standard",
        description="OpenAI Whisper transcription model",
        supports_streaming=False,
    ),
    # Groq Whisper
    ModelInfo(
        id="whisper-large-v3-turbo",
        name="Whisper Large v3 Turbo",
        provider_id=STTProvider.GROQ_WHISPER.value,
        quality="turbo",
        description="Ultra-fast Whisper Large v3 on Groq",
        supports_streaming=False,
    ),
    ModelInfo(
        id="whisper-large-v3",
        name="Whisper Large v3",
        provider_id=STTProvider.GROQ_WHISPER.value,
        quality="hd",
        description="High accuracy Whisper Large v3 on Groq",
        supports_streaming=False,
    ),
    # Faster Whisper (local)
    ModelInfo(
        id="large-v3",
        name="Large v3",
        provider_id=STTProvider.FASTER_WHISPER.value,
        quality="hd",
        description="Large v3 model for high accuracy",
        supports_streaming=False,
    ),
    ModelInfo(
        id="medium",
        name="Medium",
        provider_id=STTProvider.FASTER_WHISPER.value,
        quality="standard",
        description="Medium model for balanced speed/accuracy",
        supports_streaming=False,
    ),
    ModelInfo(
        id="small",
        name="Small",
        provider_id=STTProvider.FASTER_WHISPER.value,
        quality="standard",
        description="Small model for faster inference",
        supports_streaming=False,
    ),
    # Whisper Local (HuggingFace)
    ModelInfo(
        id="openai/whisper-large-v3",
        name="Whisper Large v3",
        provider_id=STTProvider.WHISPER_LOCAL.value,
        quality="hd",
        description="HuggingFace Whisper Large v3",
        supports_streaming=False,
    ),
    ModelInfo(
        id="openai/whisper-medium",
        name="Whisper Medium",
        provider_id=STTProvider.WHISPER_LOCAL.value,
        quality="standard",
        description="HuggingFace Whisper Medium",
        supports_streaming=False,
    ),
]


# =============================================================================
# Query Functions
# =============================================================================


def get_tts_providers() -> list[ProviderInfo]:
    """Get all TTS providers."""
    return _TTS_PROVIDERS.copy()


def get_tts_models(provider_id: str | None = None) -> list[ModelInfo]:
    """Get TTS models, optionally filtered by provider."""
    if provider_id is None:
        return _TTS_MODELS.copy()
    return [m for m in _TTS_MODELS if m.provider_id == provider_id]


def get_tts_voices(
    provider_id: str | None = None, model_id: str | None = None
) -> list[VoiceInfo]:
    """Get TTS voices (with any of Gemini's library listed so far),
    optionally filtered by provider and/or model."""
    from .library import KEPT

    voices = [*_TTS_VOICES, *KEPT.values()]

    if provider_id is not None:
        voices = [v for v in voices if v.provider_id == provider_id]

    if model_id is not None:
        voices = [v for v in voices if model_id in v.model_ids]

    return voices


def get_voice(voice_id: str) -> VoiceInfo | None:
    """Get a specific voice by ID (one of Gemini's library listed so far
    among them)."""
    from .library import KEPT

    return _VOICES_BY_ID.get(voice_id) or KEPT.get(voice_id)


def get_tts_model(model_id: str) -> ModelInfo | None:
    """A speech model by id; None for one the catalog does not know."""
    return _MODELS_BY_ID.get(model_id)


def steers(model_id: str) -> list[str]:
    """What a speech model's delivery instructions steer (``ModelInfo``);
    nothing for one it does not know or that ignores them."""
    found = get_tts_model(model_id)
    return list(found.steers) if found else []


def speeds(model_id: str) -> tuple[float, float] | None:
    """The speeds a speech model can be set to (``ModelInfo``); None for one
    with no speed (Gemini's)."""
    found = get_tts_model(model_id)
    return found.speeds if found else ModelInfo.model_fields["speeds"].default


def streams(model_id: str) -> bool:
    """Whether a speech model's audio can be passed on as it is made; one
    the catalog does not know is taken to be the speech endpoint's."""
    found = get_tts_model(model_id)
    return found.supports_streaming if found else True


def speaking_model(voice_id: str, model: str | None) -> str | None:
    """The model ``voice_id`` is spoken on: ``model`` when it speaks it,
    else the voice's provider's default (or its first model); None for a
    voice not in the catalog."""
    voice = get_voice(voice_id)
    if voice is None:
        return None
    if model in voice.model_ids:
        return model
    default = DEFAULT_TTS_MODELS.get(TTSProvider(voice.provider_id))
    return default if default in voice.model_ids else voice.model_ids[0]


def get_stt_providers() -> list[ProviderInfo]:
    """Get all STT providers."""
    return _STT_PROVIDERS.copy()


def get_stt_models(provider_id: str | None = None) -> list[ModelInfo]:
    """Get STT models, optionally filtered by provider."""
    if provider_id is None:
        return _STT_MODELS.copy()
    return [m for m in _STT_MODELS if m.provider_id == provider_id]


def get_current_voice_config(settings: Any) -> dict[str, Any]:
    """
    Get current voice configuration from settings.

    Args:
        settings: Application settings object

    Returns:
        Dictionary with current TTS and STT configuration
    """
    # What the services would use: the configs resolve every default
    # (a provider's own model, the profile's voice) in one place.
    tts = TTSConfig.from_settings(settings)
    stt = STTConfig.from_settings(settings)
    return {
        "tts_provider": tts.provider.value,
        "tts_model": tts.get_model(),
        "tts_voice": tts.get_voice(),
        "tts_speed": tts.speed,
        "stt_provider": stt.provider.value,
        "stt_model": stt.get_model(),
        "stt_language": stt.language,
    }
