"""
STT (Speech-to-Text) submodule.

Provides speech recognition capabilities with provider abstraction.
"""

from .config import STTConfig, get_stt_config
from .providers import (
    BaseSTTProvider,
    FasterWhisperProvider,
    GroqWhisperProvider,
    OpenAIWhisperProvider,
    WhisperLocalProvider,
    get_stt_provider,
)
from .service import STTService

__all__ = [
    # Config
    "STTConfig",
    "get_stt_config",
    # Providers
    "BaseSTTProvider",
    "OpenAIWhisperProvider",
    "WhisperLocalProvider",
    "FasterWhisperProvider",
    "GroqWhisperProvider",
    "get_stt_provider",
    # Service
    "STTService",
]
