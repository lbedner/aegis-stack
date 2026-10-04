"""
STT (Speech-to-Text) service configuration.

Configuration management for STT providers and settings.
Follows the same pattern as AIServiceConfig for consistency.
"""

from typing import Any, Self

from pydantic import BaseModel

from app.core import secrets

from ..models import (
    DEFAULT_STT_MODEL,
    DEFAULT_STT_MODELS,
    DEFAULT_STT_PROVIDER,
    STT_KEYS,
    STTProvider,
)


class STTConfig(BaseModel):
    """
    STT service configuration that integrates with main app settings.

    Provides typed access to STT configuration with validation
    and sensible defaults.
    """

    provider: STTProvider = DEFAULT_STT_PROVIDER
    model: str | None = None  # None = use provider default
    language: str | None = None  # None = auto-detect
    device: str | None = None  # For local providers: cpu, cuda, mps

    @classmethod
    def from_settings(cls, settings: Any) -> Self:
        """Create configuration from main application settings."""
        provider_str = getattr(settings, "STT_PROVIDER", DEFAULT_STT_PROVIDER.value)

        try:
            provider = STTProvider(provider_str)
        except ValueError:
            provider = DEFAULT_STT_PROVIDER

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
        return DEFAULT_STT_MODELS.get(self.provider, DEFAULT_STT_MODEL)

    async def get_api_key(self, settings: Any) -> str | None:
        """Get API key for the current provider, read now (``.env``, then the
        secrets store)."""
        key_name = STT_KEYS.get(self.provider)
        if key_name:
            return await secrets.get(key_name, source=settings)

        return None  # Local providers don't need API keys

    async def validation_errors(self, settings: Any) -> list[str]:
        """
        Validate STT configuration and return list of issues.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Check API key for cloud providers
        if key_name := STT_KEYS.get(self.provider):
            api_key = await self.get_api_key(settings)
            if not api_key:
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

    async def is_available(self, settings: Any) -> bool:
        """Check if the configured provider is available."""
        return not await self.validation_errors(settings)


def get_stt_config(settings: Any) -> STTConfig:
    """Get STT configuration from application settings."""
    return STTConfig.from_settings(settings)
