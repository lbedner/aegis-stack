"""What both AI frameworks need: the provider errors and the key check."""

from typing import Any
from app.services.ai.config import AIServiceConfig, api_key_env
from app.services.ai.models import PROVIDERS, AIProvider

# Every provider the registry describes. A tuple of its own could fall
# behind the enum; this cannot.
SUPPORTED_PROVIDERS: tuple[AIProvider, ...] = tuple(PROVIDERS)


# Where a free key comes from, for the providers that hand them out.
_FREE_KEY_HINTS: dict[AIProvider, str] = {
    AIProvider.GOOGLE: "Get a free key at: https://aistudio.google.com/app/apikey",
    AIProvider.GROQ: "Get a free key at: https://console.groq.com/keys",
}


class ProviderError(Exception):
    """Exception raised when provider setup fails."""


class ProviderNotInstalledError(ProviderError):
    """Raised when a provider's dependencies are not installed."""

    def __init__(self, provider: str, cli_command: str):
        self.provider = provider
        self.cli_command = cli_command
        super().__init__(f"{provider} provider is not installed")


def get_supported_providers() -> list[AIProvider]:
    """Get list of supported providers."""
    return list(SUPPORTED_PROVIDERS)


def require_api_key(config: AIServiceConfig, settings: Any) -> str:
    """The configured key for a keyed provider, or the ``ProviderError``
    that says which variable to set and where a free key comes from."""
    api_key = config.get_provider_config(settings).api_key
    if api_key:
        return api_key
    hint = _FREE_KEY_HINTS.get(config.provider)
    raise ProviderError(
        f"No API key configured for {config.provider.value}. "
        f"Set {api_key_env(config.provider)} environment variable. "
        + (f"{hint} " if hint else "")
        + "For free usage without API keys, try the keyless 'public' or "
        "'pollinations' providers, or Groq: https://console.groq.com/keys"
    )
