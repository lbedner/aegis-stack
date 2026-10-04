"""
TTS (Text-to-Speech) service configuration.

Configuration management for TTS providers and settings.
Follows the same pattern as STTConfig for consistency.
"""

from typing import Any, Self

from pydantic import BaseModel, Field

from app.core import secrets
from app.core.voice_settings import TTS_SPEED_MAX, TTS_SPEED_MIN, setting_default

from ..models import (
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_PROVIDER,
    DEFAULT_TTS_VOICE,
    TTS_KEYS,
    TTSProvider,
)


class TTSConfig(BaseModel):
    """
    TTS service configuration that integrates with main app settings.

    Provides typed access to TTS configuration with validation
    and sensible defaults.
    """

    provider: TTSProvider = DEFAULT_TTS_PROVIDER
    model: str | None = None  # None = use provider default
    voice: str | None = None  # None = use provider default
    speed: float = Field(
        default=setting_default("TTS_SPEED"), ge=TTS_SPEED_MIN, le=TTS_SPEED_MAX
    )
    instructions: str | None = None  # how to say it; gpt-4o models only

    @classmethod
    def from_settings(cls, settings: Any) -> Self:
        """Create configuration from main application settings."""
        provider_str = getattr(settings, "TTS_PROVIDER", DEFAULT_TTS_PROVIDER.value)

        try:
            provider = TTSProvider(provider_str)
        except ValueError:
            provider = DEFAULT_TTS_PROVIDER

        return cls(
            provider=provider,
            model=getattr(settings, "TTS_MODEL", None),
            voice=getattr(settings, "TTS_VOICE", None),
            speed=getattr(settings, "TTS_SPEED", None) or setting_default("TTS_SPEED"),
            instructions=getattr(settings, "TTS_INSTRUCTIONS", None),
        )

    def get_model(self) -> str:
        """Get the model to use, falling back to provider default."""
        if self.model:
            return self.model
        return DEFAULT_TTS_MODEL

    def get_voice(self) -> str:
        """Get the voice to use, falling back to provider default."""
        if self.voice:
            return self.voice
        return DEFAULT_TTS_VOICE

    async def get_api_key(self, settings: Any) -> str | None:
        """Get API key for the current provider, read now (``.env``, then the
        secrets store)."""
        key_name = TTS_KEYS.get(self.provider)
        if key_name:
            return await secrets.get(key_name, source=settings)

        return None  # Local providers don't need API keys

    async def validation_errors(self, settings: Any) -> list[str]:
        """
        Validate TTS configuration and return list of issues.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Check API key for cloud providers
        if key_name := TTS_KEYS.get(self.provider):
            api_key = await self.get_api_key(settings)
            if not api_key:
                errors.append(
                    f"Missing API key for {self.provider.value}. "
                    f"Set {key_name} environment variable."
                )

        return errors

    async def is_available(self, settings: Any) -> bool:
        """Check if the configured provider is available."""
        return not await self.validation_errors(settings)


def get_tts_config(settings: Any) -> TTSConfig:
    """Get TTS configuration from application settings."""
    return TTSConfig.from_settings(settings)
