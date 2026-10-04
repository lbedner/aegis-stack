"""
Voice Catalog Module

Provides in-memory catalog of voice providers, models, and voices
for TTS and STT services. This is static configuration data that
doesn't require database storage.
"""

from typing import Any

from .models import (
    INSTRUCTED_TTS_MODELS,
    STT_KEYS,
    TTS_KEYS,
    ModelInfo,
    OpenAIVoice,
    ProviderInfo,
    STTProvider,
    TTSProvider,
    VoiceCategory,
    VoiceInfo,
)
from .stt.config import STTConfig
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
]

# OpenAI's speech models: gpt-4o-mini-tts (INSTRUCTED_TTS_MODELS) takes
# delivery instructions and every voice; tts-1 and tts-1-hd take neither
# and know only nine of the voices.
_TTS_1 = ["tts-1", "tts-1-hd"]

_TTS_MODELS: list[ModelInfo] = [
    # OpenAI Models
    *(
        ModelInfo(
            id=model,
            name=model,
            provider_id=TTSProvider.OPENAI.value,
            description="Takes delivery instructions and every voice",
            supports_streaming=True,
            max_input_chars=4096,
        )
        for model in INSTRUCTED_TTS_MODELS
    ),
    ModelInfo(
        id="tts-1",
        name="TTS-1",
        provider_id=TTSProvider.OPENAI.value,
        quality="standard",
        description="Standard quality, lower latency",
        supports_streaming=True,
        max_input_chars=4096,  # OpenAI TTS limit
    ),
    ModelInfo(
        id="tts-1-hd",
        name="TTS-1 HD",
        provider_id=TTSProvider.OPENAI.value,
        quality="hd",
        description="High definition quality",
        supports_streaming=True,
        max_input_chars=4096,  # OpenAI TTS limit
    ),
]


def _openai_voice(
    voice: OpenAIVoice,
    description: str,
    category: VoiceCategory | None = None,
    gender: str | None = None,
    tts_1: bool = True,
) -> VoiceInfo:
    return VoiceInfo(
        id=voice.value,
        name=voice.value.title(),
        provider_id=TTSProvider.OPENAI.value,
        model_ids=INSTRUCTED_TTS_MODELS + (_TTS_1 if tts_1 else []),
        description=description,
        category=category,
        gender=gender,
    )


# The one list of OpenAI's voices: the voice API lists it, and a voice
# profile picks from it. Marin and cedar, the recommended two, lead.
_TTS_VOICES: list[VoiceInfo] = [
    _openai_voice(OpenAIVoice.MARIN, "OpenAI's recommended voice", tts_1=False),
    _openai_voice(OpenAIVoice.CEDAR, "OpenAI's recommended voice", tts_1=False),
    _openai_voice(
        OpenAIVoice.ALLOY, "Neutral, balanced voice", VoiceCategory.NEUTRAL, "neutral"
    ),
    _openai_voice(OpenAIVoice.ASH, "OpenAI voice"),
    _openai_voice(OpenAIVoice.BALLAD, "OpenAI voice", tts_1=False),
    _openai_voice(OpenAIVoice.CORAL, "OpenAI voice"),
    _openai_voice(OpenAIVoice.ECHO, "Warm, friendly voice", VoiceCategory.WARM, "male"),
    _openai_voice(
        OpenAIVoice.FABLE,
        "British-accented, narrative voice",
        VoiceCategory.EXPRESSIVE,
        "male",
    ),
    _openai_voice(
        OpenAIVoice.NOVA, "Energetic, youthful voice", VoiceCategory.ENERGETIC, "female"
    ),
    _openai_voice(
        OpenAIVoice.ONYX,
        "Deep, authoritative voice",
        VoiceCategory.AUTHORITATIVE,
        "male",
    ),
    _openai_voice(OpenAIVoice.SAGE, "OpenAI voice"),
    _openai_voice(
        OpenAIVoice.SHIMMER,
        "Clear, expressive voice",
        VoiceCategory.EXPRESSIVE,
        "female",
    ),
    _openai_voice(OpenAIVoice.VERSE, "OpenAI voice", tts_1=False),
]

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
    """Get TTS voices, optionally filtered by provider and/or model."""
    voices = _TTS_VOICES.copy()

    if provider_id is not None:
        voices = [v for v in voices if v.provider_id == provider_id]

    if model_id is not None:
        voices = [v for v in voices if model_id in v.model_ids]

    return voices


def get_voice(voice_id: str) -> VoiceInfo | None:
    """Get a specific voice by ID."""
    for voice in _TTS_VOICES:
        if voice.id == voice_id:
            return voice
    return None


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
