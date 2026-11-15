"""How providers read and what they need, beside the provider registry
(``app.services.ai.models.PROVIDERS``): which take no key, how each name
reads to a person, and where each brand lives (its homepage, the domain
its logo is fetched from)."""

from typing import Any

from app.services.ai.models import AIProvider

# Providers that take no key from settings: keyless endpoints and a local
# server. The one list; configuration checks and every readiness report
# read it.
# Providers served by the inference component, each by the engine of its
# name (``app.components.inference``): free, on this machine.
LOCAL_PROVIDERS = frozenset({AIProvider.OLLAMA, AIProvider.LLAMACPP})
KEYLESS_PROVIDERS = (
    frozenset({AIProvider.PUBLIC, AIProvider.POLLINATIONS}) | LOCAL_PROVIDERS
)


def local_base_url(provider: AIProvider, settings: Any) -> str:
    """A local provider's OpenAI-compatible API, at the setting its engine
    reads too (``<provider>_base_url_effective``)."""
    return f"{getattr(settings, f'{provider.value}_base_url_effective')}/v1"

# How a provider's name reads to a person, where title case gets it wrong.
_PROVIDER_LABELS = {
    AIProvider.OPENAI: "OpenAI",
    AIProvider.OPENROUTER: "OpenRouter",
    AIProvider.PUBLIC: "LLM7.io",
    AIProvider.LLAMACPP: "llama.cpp",
}


def provider_label(provider: AIProvider) -> str:
    """``openai`` reads "OpenAI"; most read as their name, capitalized."""
    return _PROVIDER_LABELS.get(provider, provider.value.title())


# Each brand's home: the domain the catalog sync fetches its logo from.
_PROVIDER_HOMEPAGES = {
    AIProvider.OPENAI: "https://openai.com",
    AIProvider.ANTHROPIC: "https://www.anthropic.com",
    AIProvider.GOOGLE: "https://ai.google.dev",
    AIProvider.GROQ: "https://groq.com",
    AIProvider.MISTRAL: "https://mistral.ai",
    AIProvider.COHERE: "https://cohere.com",
    AIProvider.OLLAMA: "https://ollama.com",
    AIProvider.LLAMACPP: "https://github.com/ggml-org/llama.cpp",
    AIProvider.PUBLIC: "https://llm7.io",
    AIProvider.POLLINATIONS: "https://pollinations.ai",
    AIProvider.OPENROUTER: "https://openrouter.ai",
}


def provider_homepage(provider: AIProvider) -> str | None:
    return _PROVIDER_HOMEPAGES.get(provider)
