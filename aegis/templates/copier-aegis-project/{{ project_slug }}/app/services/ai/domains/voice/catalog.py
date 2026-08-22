"""
Voice Catalog Module

Provides in-memory catalog of voice providers, models, and voices
for TTS and STT services. This is static configuration data that
doesn't require database storage.
"""

from typing import Any

from .models import (
    ModelInfo,
    OpenAIVoice,
    ProviderInfo,
    STTProvider,
    TTSProvider,
    VoiceCategory,
    VoiceInfo,
)

# =============================================================================
# TTS Catalog Data
# =============================================================================

_TTS_PROVIDERS: list[ProviderInfo] = [
    ProviderInfo(
        id=TTSProvider.OPENAI.value,
        name="OpenAI",
        type="tts",
        requires_api_key=True,
        api_key_env_var="OPENAI_API_KEY",
        is_local=False,
        description="OpenAI Text-to-Speech API with natural-sounding voices",
    ),
]

_TTS_MODELS: list[ModelInfo] = [
    # OpenAI Models
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

_TTS_VOICES: list[VoiceInfo] = [
    # OpenAI Voices - descriptions from models.py comments
    VoiceInfo(
        id=OpenAIVoice.ALLOY.value,
        name="Alloy",
        provider_id=TTSProvider.OPENAI.value,
        model_ids=["tts-1", "tts-1-hd"],
        description="Neutral, balanced voice",
        category=VoiceCategory.NEUTRAL,
        gender="neutral",
    ),
    VoiceInfo(
        id=OpenAIVoice.ECHO.value,
        name="Echo",
        provider_id=TTSProvider.OPENAI.value,
        model_ids=["tts-1", "tts-1-hd"],
        description="Warm, friendly voice",
        category=VoiceCategory.WARM,
        gender="male",
    ),
    VoiceInfo(
        id=OpenAIVoice.FABLE.value,
        name="Fable",
        provider_id=TTSProvider.OPENAI.value,
        model_ids=["tts-1", "tts-1-hd"],
        description="British-accented, narrative voice",
        category=VoiceCategory.EXPRESSIVE,
        gender="male",
    ),
    VoiceInfo(
        id=OpenAIVoice.ONYX.value,
        name="Onyx",
        provider_id=TTSProvider.OPENAI.value,
        model_ids=["tts-1", "tts-1-hd"],
        description="Deep, authoritative voice",
        category=VoiceCategory.AUTHORITATIVE,
        gender="male",
    ),
    VoiceInfo(
        id=OpenAIVoice.NOVA.value,
        name="Nova",
        provider_id=TTSProvider.OPENAI.value,
        model_ids=["tts-1", "tts-1-hd"],
        description="Energetic, youthful voice",
        category=VoiceCategory.ENERGETIC,
        gender="female",
    ),
    VoiceInfo(
        id=OpenAIVoice.SHIMMER.value,
        name="Shimmer",
        provider_id=TTSProvider.OPENAI.value,
        model_ids=["tts-1", "tts-1-hd"],
        description="Clear, expressive voice",
        category=VoiceCategory.EXPRESSIVE,
        gender="female",
    ),
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
        api_key_env_var="OPENAI_API_KEY",
        is_local=False,
        description="OpenAI Whisper API for accurate transcription",
    ),
    ProviderInfo(
        id=STTProvider.GROQ_WHISPER.value,
        name="Groq Whisper",
        type="stt",
        requires_api_key=True,
        api_key_env_var="GROQ_API_KEY",
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
    # OpenAI Whisper
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
    # Get values with defaults, filtering out None for required fields
    tts_provider = getattr(settings, "TTS_PROVIDER", None) or TTSProvider.OPENAI.value
    tts_model = getattr(settings, "TTS_MODEL", None) or "tts-1"
    tts_voice = getattr(settings, "TTS_VOICE", None) or OpenAIVoice.ALLOY.value
    tts_speed = getattr(settings, "TTS_SPEED", None) or 1.0
    stt_provider = (
        getattr(settings, "STT_PROVIDER", None) or STTProvider.OPENAI_WHISPER.value
    )
    stt_model = getattr(settings, "STT_MODEL", None) or "whisper-1"
    stt_language = getattr(settings, "STT_LANGUAGE", None)

    return {
        "tts_provider": tts_provider,
        "tts_model": tts_model,
        "tts_voice": tts_voice,
        "tts_speed": tts_speed,
        "stt_provider": stt_provider,
        "stt_model": stt_model,
        "stt_language": stt_language,
    }
