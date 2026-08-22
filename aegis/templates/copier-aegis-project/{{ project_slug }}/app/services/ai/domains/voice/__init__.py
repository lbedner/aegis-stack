"""
Voice module for AI service.

Provides Speech-to-Text (STT) and Text-to-Speech (TTS) capabilities
with provider abstraction supporting multiple cloud and open-source providers.

Submodules:
    - tts/: Text-to-Speech services, config, and providers
    - stt/: Speech-to-Text services, config, and providers
"""

# TTS submodule imports
# Catalog query functions
from .catalog import (
    get_current_voice_config,
    get_stt_models,
    get_stt_providers,
    get_tts_models,
    get_tts_providers,
    get_tts_voices,
    get_voice,
)

# Shared models
from .models import (
    AudioFormat,
    AudioInput,
    ModelInfo,
    OpenAIVoice,
    ProviderInfo,
    SpeechRequest,
    SpeechResult,
    STTProvider,
    TranscriptionResult,
    TranscriptionSegment,
    TTSProvider,
    VoiceCategory,
    VoiceChatResponse,
    VoiceInfo,
    VoicePreviewRequest,
    VoiceSettingsResponse,
    VoiceSettingsUpdate,
)

# STT submodule imports
from .stt import (
    BaseSTTProvider,
    FasterWhisperProvider,
    GroqWhisperProvider,
    OpenAIWhisperProvider,
    STTConfig,
    STTService,
    WhisperLocalProvider,
    get_stt_config,
    get_stt_provider,
)
from .tts import (
    BaseTTSProvider,
    OpenAITTSProvider,
    TTSConfig,
    TTSService,
    get_tts_config,
    get_tts_provider,
)

__all__ = [
    # STT Config
    "STTConfig",
    "get_stt_config",
    # TTS Config
    "TTSConfig",
    "get_tts_config",
    # Core Models
    "STTProvider",
    "TTSProvider",
    "OpenAIVoice",
    "AudioFormat",
    "AudioInput",
    "TranscriptionSegment",
    "TranscriptionResult",
    "SpeechRequest",
    "SpeechResult",
    "VoiceChatResponse",
    # Catalog Models
    "VoiceCategory",
    "ProviderInfo",
    "ModelInfo",
    "VoiceInfo",
    "VoiceSettingsResponse",
    "VoiceSettingsUpdate",
    "VoicePreviewRequest",
    # STT Providers
    "BaseSTTProvider",
    "OpenAIWhisperProvider",
    "WhisperLocalProvider",
    "FasterWhisperProvider",
    "GroqWhisperProvider",
    "get_stt_provider",
    # TTS Providers
    "BaseTTSProvider",
    "OpenAITTSProvider",
    "get_tts_provider",
    # Services
    "STTService",
    "TTSService",
    # Catalog Query Functions
    "get_tts_providers",
    "get_tts_models",
    "get_tts_voices",
    "get_voice",
    "get_stt_providers",
    "get_stt_models",
    "get_current_voice_config",
]
