"""
TTS (Text-to-Speech) submodule.

Provides speech synthesis capabilities with provider abstraction.
"""

from .config import TTSConfig, get_tts_config
from .providers import (
    BaseTTSProvider,
    OpenAITTSProvider,
    get_tts_provider,
)
from .service import TTSService

__all__ = [
    # Config
    "TTSConfig",
    "get_tts_config",
    # Providers
    "BaseTTSProvider",
    "OpenAITTSProvider",
    "get_tts_provider",
    # Service
    "TTSService",
]
