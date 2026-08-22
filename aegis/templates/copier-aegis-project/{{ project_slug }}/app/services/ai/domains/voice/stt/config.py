"""
STT (Speech-to-Text) service configuration.

Configuration management for STT providers and settings.
Follows the same pattern as AIServiceConfig for consistency.
"""

from typing import Any

from pydantic import BaseModel, Field

from ..models import STTProvider


class STTConfig(BaseModel):
    """
    STT service configuration that integrates with main app settings.

    Provides typed access to STT configuration with validation
    and sensible defaults.
    """

    provider: STTProvider = STTProvider.OPENAI_WHISPER
    model: str | None = None  # None = use provider default
    language: str | None = None  # None = auto-detect
    device: str | None = None  # For local providers: cpu, cuda, mps

    # Provider-specific defaults
    DEFAULT_MODELS: dict[STTProvider, str] = Field(
        default={
            STTProvider.OPENAI_WHISPER: "whisper-1",
            STTProvider.GROQ_WHISPER: "whisper-large-v3-turbo",
            STTProvider.WHISPER_LOCAL: "openai/whisper-base",
            STTProvider.FASTER_WHISPER: "base",
        },
        exclude=True,
    )

    @classmethod
    def from_settings(cls, settings: Any) -> "STTConfig":
        """Create configuration from main application settings."""
        provider_str = getattr(settings, "STT_PROVIDER", "openai_whisper")

        try:
            provider = STTProvider(provider_str)
        except ValueError:
            provider = STTProvider.OPENAI_WHISPER

        return cls(
            provider=provider,
            model=getattr(settings, "STT_MODEL", None),
            language=getattr(settings, "STT_LANGUAGE", None),
            device=getattr(settings, "STT_DEVICE", None),
        )

    def get_model(self) -> str:
        """Get the model to use, falling back to provider default."""
        if self.model:
            return self.model
        return self.DEFAULT_MODELS.get(self.provider, "whisper-1")

    def get_api_key(self, settings: Any) -> str | None:
        """Get API key for the current provider."""
        api_key_mapping = {
            STTProvider.OPENAI_WHISPER: "OPENAI_API_KEY",
            STTProvider.GROQ_WHISPER: "GROQ_API_KEY",
        }

        key_name = api_key_mapping.get(self.provider)
        if key_name:
            return getattr(settings, key_name, None)

        return None  # Local providers don't need API keys

    def validate(self, settings: Any) -> list[str]:
        """
        Validate STT configuration and return list of issues.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Check API key for cloud providers
        cloud_providers = {STTProvider.OPENAI_WHISPER, STTProvider.GROQ_WHISPER}

        if self.provider in cloud_providers:
            api_key = self.get_api_key(settings)
            if not api_key:
                key_name = {
                    STTProvider.OPENAI_WHISPER: "OPENAI_API_KEY",
                    STTProvider.GROQ_WHISPER: "GROQ_API_KEY",
                }.get(self.provider)
                errors.append(
                    f"Missing API key for {self.provider.value}. "
                    f"Set {key_name} environment variable."
                )

        # Validate language code format if provided
        if self.language and len(self.language) != 2:
            errors.append(
                f"Invalid language code '{self.language}'. "
                "Use ISO 639-1 format (e.g., 'en', 'es', 'fr')."
            )

        return errors

    def is_available(self, settings: Any) -> bool:
        """Check if the configured provider is available."""
        return len(self.validate(settings)) == 0


def get_stt_config(settings: Any) -> STTConfig:
    """Get STT configuration from application settings."""
    return STTConfig.from_settings(settings)
