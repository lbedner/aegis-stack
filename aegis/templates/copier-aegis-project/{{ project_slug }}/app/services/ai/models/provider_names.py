"""How providers read and what they need, beside the provider registry
(``app.services.ai.models.PROVIDERS``): which take no key, how each name
reads to a person, and where each brand lives (its homepage, the domain
its logo is fetched from)."""

from app.services.ai.models import AIProvider

# Providers that take no key from settings: keyless endpoints and a local
# server. The one list; configuration checks and every readiness report
# read it.
KEYLESS_PROVIDERS = frozenset(
    {AIProvider.PUBLIC, AIProvider.OLLAMA, AIProvider.POLLINATIONS}
)

# How a provider's name reads to a person, where title case gets it wrong.
_PROVIDER_LABELS = {
    AIProvider.OPENAI: "OpenAI",
    AIProvider.OPENROUTER: "OpenRouter",
    AIProvider.PUBLIC: "LLM7.io",
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
    AIProvider.PUBLIC: "https://llm7.io",
    AIProvider.POLLINATIONS: "https://pollinations.ai",
    AIProvider.OPENROUTER: "https://openrouter.ai",
}


def provider_homepage(provider: AIProvider) -> str | None:
    return _PROVIDER_HOMEPAGES.get(provider)
