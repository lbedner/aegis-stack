"""
TTS (Text-to-Speech) service configuration.

Configuration management for TTS providers and settings.
Follows the same pattern as STTConfig for consistency.
"""

from typing import Any

from pydantic import BaseModel, Field

from ..models import TTSProvider


class TTSConfig(BaseModel):
    """
    TTS service configuration that integrates with main app settings.

    Provides typed access to TTS configuration with validation
    and sensible defaults.
    """

    provider: TTSProvider = TTSProvider.OPENAI
    model: str | None = None  # None = use provider default
    voice: str | None = None  # None = use provider default
    speed: float = Field(default=1.0, ge=0.25, le=4.0)

    # Provider-specific defaults
    DEFAULT_MODELS: dict[TTSProvider, str] = Field(
        default={
            TTSProvider.OPENAI: "tts-1",
        },
        exclude=True,
    )

    DEFAULT_VOICES: dict[TTSProvider, str] = Field(
        default={
            TTSProvider.OPENAI: "alloy",
        },
        exclude=True,
    )

    @classmethod
    def from_settings(cls, settings: Any) -> "TTSConfig":
        """Create configuration from main application settings."""
        provider_str = getattr(settings, "TTS_PROVIDER", "openai")

        try:
            provider = TTSProvider(provider_str)
        except ValueError:
            provider = TTSProvider.OPENAI

        return cls(
            provider=provider,
            model=getattr(settings, "TTS_MODEL", None),
            voice=getattr(settings, "TTS_VOICE", None),
            speed=getattr(settings, "TTS_SPEED", 1.0),
        )

    def get_model(self) -> str:
        """Get the model to use, falling back to provider default."""
        if self.model:
            return self.model
        return self.DEFAULT_MODELS.get(self.provider, "tts-1")

    def get_voice(self) -> str:
        """Get the voice to use, falling back to provider default."""
        if self.voice:
            return self.voice
        return self.DEFAULT_VOICES.get(self.provider, "alloy")

    def get_api_key(self, settings: Any) -> str | None:
        """Get API key for the current provider."""
        api_key_mapping = {
            TTSProvider.OPENAI: "OPENAI_API_KEY",
        }

        key_name = api_key_mapping.get(self.provider)
        if key_name:
            return getattr(settings, key_name, None)

        return None  # Local providers don't need API keys

    def validate(self, settings: Any) -> list[str]:
        """
        Validate TTS configuration and return list of issues.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Check API key for cloud providers
        cloud_providers = {TTSProvider.OPENAI}

        if self.provider in cloud_providers:
            api_key = self.get_api_key(settings)
            if not api_key:
                key_name = {
                    TTSProvider.OPENAI: "OPENAI_API_KEY",
                }.get(self.provider)
                errors.append(
                    f"Missing API key for {self.provider.value}. "
                    f"Set {key_name} environment variable."
                )

        # Validate speed range
        if not 0.25 <= self.speed <= 4.0:
            errors.append(
                f"Invalid speed '{self.speed}'. Must be between 0.25 and 4.0."
            )

        return errors

    def is_available(self, settings: Any) -> bool:
        """Check if the configured provider is available."""
        return len(self.validate(settings)) == 0


def get_tts_config(settings: Any) -> TTSConfig:
    """Get TTS configuration from application settings."""
    return TTSConfig.from_settings(settings)
