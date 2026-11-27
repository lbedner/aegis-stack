"""
STT (Speech-to-Text) submodule.

Provides speech recognition capabilities with provider abstraction.
"""

from .config import STTConfig, get_stt_config
from .providers import (
    BaseSTTProvider,
    GroqWhisperProvider,
    OpenAIWhisperProvider,
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
    "GroqWhisperProvider",
    "get_stt_provider",
    # Service
    "STTService",
]
