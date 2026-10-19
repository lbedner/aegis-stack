"""The providers the AI service can run on (``PROVIDERS``): each one's
name (``AIProvider``), what it can do, its key and how its model is built.
In code, not a table: what a provider is has to be knowable before any
storage exists (the memory backend has none)."""

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel


class AIProvider(str, Enum):
    """Supported AI providers for PydanticAI integration."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    GROQ = "groq"
    MISTRAL = "mistral"
    COHERE = "cohere"
    OLLAMA = "ollama"  # Local LLM inference via Ollama
    PUBLIC = "public"  # LLM7.io: keyless anonymous tier; key unlocks premium
    POLLINATIONS = "pollinations"  # Pollinations: keyless anonymous tier
    OPENROUTER = "openrouter"  # Aggregator; speaks the OpenAI API

    @classmethod
    def from_name(cls, value: object) -> "AIProvider | None":
        """Resolve a provider id or vendor display name to an AIProvider.

        Accepts the canonical value ("public"), case-insensitively, plus
        known vendor display-name aliases ("LLM7.io" -> public). Returns
        ``None`` when the value maps to no provider, so callers fall back or
        skip rather than crash. A bad ``AI_PROVIDER`` must never brick boot,
        and model auto-detect must never persist a non-enum value.
        """
        if not value:
            return None
        norm = str(value).strip().lower()
        aliases = {
            "llm7.io": cls.PUBLIC.value,
            "llm7": cls.PUBLIC.value,
            "unknown": cls.PUBLIC.value,
            "pollinations.ai": cls.POLLINATIONS.value,
        }
        norm = aliases.get(norm, norm)
        try:
            return cls(norm)
        except ValueError:
            return None


class ProviderConfig(BaseModel):
    """Configuration for a specific AI provider."""

    name: AIProvider
    api_key: str | None = None
    base_url: str | None = None
    max_tokens: int = 1000
    temperature: float = 0.7
    timeout_seconds: float = 120.0


class ProviderCapabilities(BaseModel):
    """Capabilities for an AI provider (binary features only)."""

    provider: AIProvider
    supports_streaming: bool = True
    supports_function_calling: bool = False
    supports_vision: bool = False
    free_tier_available: bool = False


# Provider capability definitions (binary features only)
PROVIDER_CAPABILITIES = {
    AIProvider.OPENAI: ProviderCapabilities(
        provider=AIProvider.OPENAI,
        supports_streaming=True,
        supports_function_calling=True,
        supports_vision=True,
        free_tier_available=False,
    ),
    AIProvider.ANTHROPIC: ProviderCapabilities(
        provider=AIProvider.ANTHROPIC,
        supports_streaming=True,
        supports_function_calling=True,
        supports_vision=True,
        free_tier_available=False,
    ),
    AIProvider.GOOGLE: ProviderCapabilities(
        provider=AIProvider.GOOGLE,
        supports_streaming=True,
        supports_function_calling=True,
        supports_vision=True,
        free_tier_available=False,
    ),
    AIProvider.GROQ: ProviderCapabilities(
        provider=AIProvider.GROQ,
        supports_streaming=True,
        supports_function_calling=False,
        supports_vision=False,
        free_tier_available=False,
    ),
    AIProvider.MISTRAL: ProviderCapabilities(
        provider=AIProvider.MISTRAL,
        supports_streaming=True,
        supports_function_calling=True,
        supports_vision=False,
        free_tier_available=False,
    ),
    AIProvider.COHERE: ProviderCapabilities(
        provider=AIProvider.COHERE,
        supports_streaming=True,
        supports_function_calling=False,
        supports_vision=False,
        free_tier_available=False,
    ),
    AIProvider.OLLAMA: ProviderCapabilities(
        provider=AIProvider.OLLAMA,
        supports_streaming=True,
        supports_function_calling=False,
        supports_vision=False,
        free_tier_available=True,  # Local models, no API key required
    ),
    AIProvider.PUBLIC: ProviderCapabilities(
        provider=AIProvider.PUBLIC,
        supports_streaming=False,
        supports_function_calling=False,
        supports_vision=False,
        free_tier_available=True,  # Anonymous tier (open-weight models)
    ),
    AIProvider.POLLINATIONS: ProviderCapabilities(
        provider=AIProvider.POLLINATIONS,
        supports_streaming=False,  # Anonymous tier rejects stream=true
        supports_function_calling=False,
        supports_vision=False,
        free_tier_available=True,  # Anonymous tier (open-weight models)
    ),
    AIProvider.OPENROUTER: ProviderCapabilities(
        provider=AIProvider.OPENROUTER,
        supports_streaming=True,
        supports_function_calling=True,
        # Depends on the model it routes to, not on OpenRouter: the
        # aggregator itself passes vision through.
        supports_vision=True,
        free_tier_available=False,
    ),
}


@dataclass(frozen=True)
class ProviderSpec:
    """Everything about one provider, in one place.

    This used to be six: the enum, the capabilities table, an API-key
    lookup in ``config``, a model-class if/elif, and two byte-identical
    env-var maps. Adding a provider meant five edits across three files,
    and missing one failed quietly at the point of use.

    It stays in CODE rather than a table because this stack runs its AI
    on a memory backend with no database; what a provider is has to be
    knowable before any storage exists.

    ``model`` is a lazy ``(module, class)`` pair: the SDK for a provider
    nobody selected must not be imported, let alone required.
    ``base_url`` marks the OpenAI-compatible ones - they need no class of
    their own, only somewhere else to point.
    """

    env_var: str
    capabilities: ProviderCapabilities
    model: tuple[str, str] | None = None
    base_url: str | None = None
    # What to install for it, and the module whose presence proves it is
    # installed. Most ride the OpenAI SDK, because most speak its API.
    dependency: str = "pydantic-ai-slim[openai]"
    module: str = "openai"
    # Where a person goes to get a key; None for the keyless endpoints
    # and for a local server.
    key_url: str | None = None
    # Cannot be built by a plain constructor call: a keyless endpoint, or
    # a local server whose address comes from settings. It still has a
    # model class - ``get_agent`` uses it - but ``model_for`` refuses.
    builds_own_client: bool = False


_OPENAI_CHAT = ("pydantic_ai.models.openai", "OpenAIChatModel")

PROVIDERS: dict[AIProvider, ProviderSpec] = {
    AIProvider.OPENAI: ProviderSpec(
        env_var="OPENAI_API_KEY",
        capabilities=PROVIDER_CAPABILITIES[AIProvider.OPENAI],
        # The Responses API, not Chat Completions: OpenAI's reasoning
        # models reject function tools on /v1/chat/completions.
        model=("pydantic_ai.models.openai", "OpenAIResponsesModel"),
        dependency="pydantic-ai-slim[openai]",
        module="openai",
        key_url="https://platform.openai.com/api-keys",
    ),
    AIProvider.ANTHROPIC: ProviderSpec(
        env_var="ANTHROPIC_API_KEY",
        capabilities=PROVIDER_CAPABILITIES[AIProvider.ANTHROPIC],
        model=("pydantic_ai.models.anthropic", "AnthropicModel"),
        dependency="pydantic-ai-slim[anthropic]",
        module="anthropic",
        key_url="https://console.anthropic.com/",
    ),
    AIProvider.GOOGLE: ProviderSpec(
        env_var="GOOGLE_API_KEY",
        capabilities=PROVIDER_CAPABILITIES[AIProvider.GOOGLE],
        model=("pydantic_ai.models.google", "GoogleModel"),
        dependency="pydantic-ai-slim[google]",
        module="google.genai",
        key_url="https://aistudio.google.com/app/apikey",
    ),
    AIProvider.GROQ: ProviderSpec(
        env_var="GROQ_API_KEY",
        capabilities=PROVIDER_CAPABILITIES[AIProvider.GROQ],
        model=("pydantic_ai.models.groq", "GroqModel"),
        dependency="pydantic-ai-slim[groq]",
        module="groq",
        key_url="https://console.groq.com/keys",
    ),
    AIProvider.MISTRAL: ProviderSpec(
        env_var="MISTRAL_API_KEY",
        capabilities=PROVIDER_CAPABILITIES[AIProvider.MISTRAL],
        model=_OPENAI_CHAT,
        base_url="https://api.mistral.ai/v1",
        key_url="https://console.mistral.ai/api-keys/",
    ),
    AIProvider.COHERE: ProviderSpec(
        env_var="COHERE_API_KEY",
        capabilities=PROVIDER_CAPABILITIES[AIProvider.COHERE],
        model=_OPENAI_CHAT,
        base_url="https://api.cohere.ai/v1",
        key_url="https://dashboard.cohere.com/api-keys",
    ),
    AIProvider.OLLAMA: ProviderSpec(
        env_var="OLLAMA_API_KEY",
        capabilities=PROVIDER_CAPABILITIES[AIProvider.OLLAMA],
        model=_OPENAI_CHAT,
        # Its address is a setting, not a constant, so the model is built
        # rather than described.
        builds_own_client=True,
    ),
    AIProvider.PUBLIC: ProviderSpec(
        env_var="LLM7_API_KEY",
        capabilities=PROVIDER_CAPABILITIES[AIProvider.PUBLIC],
        # It has a class like any other; what it lacks is a plain
        # constructor call, because the endpoint is keyless and the
        # client is built around that.
        model=_OPENAI_CHAT,
        builds_own_client=True,
    ),
    AIProvider.POLLINATIONS: ProviderSpec(
        env_var="POLLINATIONS_API_KEY",
        capabilities=PROVIDER_CAPABILITIES[AIProvider.POLLINATIONS],
        # It has a class like any other; what it lacks is a plain
        # constructor call, because the endpoint is keyless and the
        # client is built around that.
        model=_OPENAI_CHAT,
        builds_own_client=True,
    ),
    AIProvider.OPENROUTER: ProviderSpec(
        # NOT OPENAI_API_KEY. pydantic-ai's OpenAI client reads that from
        # the environment, so borrowing it would have OpenRouter overwrite
        # a real OpenAI key for the rest of the process.
        env_var="OPEN_ROUTER_API_KEY",
        capabilities=PROVIDER_CAPABILITIES[AIProvider.OPENROUTER],
        model=_OPENAI_CHAT,
        base_url="https://openrouter.ai/api/v1",
        key_url="https://openrouter.ai/keys",
    ),
}


def get_provider_capabilities(provider: AIProvider) -> ProviderCapabilities:
    """Get capabilities for a specific provider."""
    return PROVIDER_CAPABILITIES.get(provider, ProviderCapabilities(provider=provider))


def get_free_providers() -> list[AIProvider]:
    """Get list of providers that offer free tiers."""
    return [
        provider
        for provider, caps in PROVIDER_CAPABILITIES.items()
        if caps.free_tier_available
    ]
