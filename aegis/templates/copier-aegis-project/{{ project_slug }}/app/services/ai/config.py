"""
AI service configuration models.

Configuration management for AI service providers, models, and settings.
Integrates with main application settings through app.core.config.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import (
    PROVIDERS,
    AIProvider,
    ProviderConfig,
    get_provider_capabilities,
)


def _resolve_provider(value: object) -> AIProvider:
    """Coerce a configured AI_PROVIDER to a valid AIProvider, never crashing.

    A bad ``.env`` value (e.g. a vendor display name like ``llm7.io`` written
    by model auto-detect) must not crash-loop the webserver. Falls back to
    ``public`` with a warning when the value does not resolve.
    """
    resolved = AIProvider.from_name(value)
    if resolved is None:
        from app.core.log import logger

        logger.warning(
            "Unknown AI_PROVIDER %r; falling back to 'public'. Valid: %s",
            value,
            ", ".join(p.value for p in AIProvider),
        )
        return AIProvider.PUBLIC
    return resolved


_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


def _resolve_effort(value: object) -> str | None:
    """Coerce a configured AI_EFFORT to a valid level, never crashing.

    Same contract as ``_resolve_provider``: a typo in ``.env`` must not
    crash-loop the webserver. Falls back to None (the API default) with a
    warning. Anthropic-only downstream; other providers ignore it.
    """
    if value is None or value == "":
        return None
    normalized = str(value).strip().lower()
    if normalized in _EFFORT_LEVELS:
        return normalized
    from app.core.log import logger

    logger.warning(
        "Unknown AI_EFFORT %r; using the API default. Valid: %s",
        value,
        ", ".join(_EFFORT_LEVELS),
    )
    return None


# The settings field / environment variable each keyed provider reads its
# API key from. Providers absent here need no key from settings.
# Where each provider's key lives, from the one place a provider is
# described. It was a map of its own; a provider named here and nowhere
# else would have gone unnoticed until somebody selected it.
API_KEY_ENV: dict[AIProvider, str] = {
    p: spec.env_var for p, spec in PROVIDERS.items()
}


def api_key_env(provider: AIProvider) -> str:
    """The environment variable named in "set X to use this provider" copy."""
    return API_KEY_ENV.get(provider, f"{provider.value.upper()}_API_KEY")


class AIServiceConfig(BaseModel):
    """
    AI service configuration that integrates with main app settings.

    This class provides convenience methods and validation for AI service
    configuration while the actual settings live in app.core.config.Settings.
    """

    enabled: bool = True
    provider: AIProvider = (
        AIProvider.PUBLIC
    )  # Default to public endpoints (LLM7.io free anonymous tier)
    model: str = "gpt-3.5-turbo"  # Default to widely supported model
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    # Anthropic-only: thinking depth / output-token spend. None = the API
    # default. Ignored by non-Anthropic providers.
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    max_tokens: int = Field(default=1000, gt=0, le=8000)
    timeout_seconds: float = Field(default=120.0, gt=0)

    # RAG-Chat integration settings (used when RAG is enabled)
    rag_default_collection: str = "default"
    rag_top_k: int = Field(default=10, gt=0, le=50)
    rag_min_score: float = Field(default=0.1, ge=0.0, le=1.0)

    @classmethod
    def from_settings(cls, settings: Any) -> "AIServiceConfig":
        """Create configuration from main application settings."""
        return cls(
            enabled=getattr(settings, "AI_ENABLED", True),
            provider=_resolve_provider(getattr(settings, "AI_PROVIDER", "public")),
            model=getattr(settings, "AI_MODEL", "gpt-3.5-turbo"),
            temperature=getattr(settings, "AI_TEMPERATURE", 0.7),
            effort=_resolve_effort(getattr(settings, "AI_EFFORT", None)),
            max_tokens=getattr(settings, "AI_MAX_TOKENS", 1000),
            timeout_seconds=getattr(settings, "AI_TIMEOUT_SECONDS", 120.0),
            # RAG-Chat integration settings
            rag_default_collection=getattr(
                settings, "RAG_CHAT_DEFAULT_COLLECTION", "default"
            ),
            rag_top_k=getattr(settings, "RAG_CHAT_TOP_K", 10),
            rag_min_score=getattr(settings, "RAG_CHAT_MIN_SCORE", 0.1),
        )

    def get_provider_config(self, settings: Any) -> ProviderConfig:
        """Get provider-specific configuration."""
        # Keyed providers read their key from settings; the local and
        # keyless ones (ollama, public, pollinations) read it in their own
        # provider path.
        env_var = API_KEY_ENV.get(self.provider)
        api_key = getattr(settings, env_var, None) if env_var else None

        return ProviderConfig(
            name=self.provider,
            api_key=api_key,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            timeout_seconds=self.timeout_seconds,
        )

    def validate_configuration(self, settings: Any) -> list[str]:
        """
        Validate AI service configuration and return list of issues.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if not self.enabled:
            return errors  # Skip validation if disabled

        # Check if provider is supported
        capabilities = get_provider_capabilities(self.provider)
        if not capabilities:
            errors.append(f"Unsupported provider: {self.provider}")

        # Check API key requirement (keyless providers don't need API keys)
        local_providers = {
            AIProvider.PUBLIC,
            AIProvider.OLLAMA,
            AIProvider.POLLINATIONS,
        }
        provider_config = self.get_provider_config(settings)

        if self.provider not in local_providers and not provider_config.api_key:
            errors.append(
                f"Missing API key for {self.provider} provider. "
                f"Set {self.provider.upper()}_API_KEY environment variable."
            )

        # Note: Token limits vary by model within each provider,
        # so we don't validate them here

        return errors

    def is_provider_available(self, settings: Any) -> bool:
        """Check if the configured provider is available and properly configured."""
        errors = self.validate_configuration(settings)
        return len(errors) == 0

    def get_available_providers(self, settings: Any) -> list[AIProvider]:
        """Get list of providers that are properly configured."""
        available = []

        for provider in AIProvider:
            # Temporarily check each provider
            temp_config = AIServiceConfig(
                enabled=True,
                provider=provider,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            if len(temp_config.validate_configuration(settings)) == 0:
                available.append(provider)

        return available


def get_ai_config(settings: Any) -> AIServiceConfig:
    """Get AI service configuration from application settings."""
    return AIServiceConfig.from_settings(settings)
