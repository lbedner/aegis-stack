"""Building a PydanticAI model for a provider."""

from typing import Any
from app.services.ai.config import AIServiceConfig, api_key_env
from app.services.ai.models import PROVIDERS, AIProvider
import importlib
import os
from collections.abc import Sequence
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from app.services.ai.domains.llm.base import (
    ProviderError,
    require_api_key,
)

def _get_model_class(provider: AIProvider):
    """The pydantic-ai model class for a provider, imported lazily.

    Lazily because a provider nobody selected must not drag its SDK in;
    from the registry because the class is a FACT about the provider and
    belongs beside the rest of them.
    """
    spec = PROVIDERS.get(provider)
    if spec is None or spec.model is None:
        raise ProviderError(f"Unsupported provider: {provider}")
    module = importlib.import_module(spec.model[0])
    return getattr(module, spec.model[1])


def _supports_custom_temperature(model: str | None) -> bool:
    """Whether a model accepts a non-default ``temperature``.

    OpenAI reasoning models (o1/o3/o4) and the gpt-5 family reject any
    temperature other than the default (1) — sending one returns a 400. Omit
    temperature for those; every other model accepts a custom value.
    """
    if not model:
        return True
    name = model.split("/")[-1].lower()  # strip any "provider/" prefix
    return not name.startswith(("o1", "o3", "o4", "gpt-5"))


def _model_settings(config: Any) -> ModelSettings:
    """Build ModelSettings for the agent, omitting ``temperature`` for models
    that only accept the default so they don't 400 (see
    ``_supports_custom_temperature``)."""
    kwargs: dict[str, Any] = {
        "max_tokens": config.max_tokens,
        "timeout": config.timeout_seconds,
    }
    if _supports_custom_temperature(config.model):
        kwargs["temperature"] = config.temperature
    # Effort is an Anthropic-only knob (thinking depth / token spend). Lazy
    # import mirrors ``_get_model_class``: the anthropic extra may not be
    # installed when another provider is configured.
    effort = getattr(config, "effort", None)
    if effort and getattr(config, "provider", None) == AIProvider.ANTHROPIC:
        from pydantic_ai.models.anthropic import AnthropicModelSettings

        return AnthropicModelSettings(anthropic_effort=effort, **kwargs)
    return ModelSettings(**kwargs)


def _ollama_model(config: AIServiceConfig, settings: Any) -> Any:
    """The model for a local Ollama server, over its OpenAI-compatible API.

    ``AsyncOpenAI``, ``OpenAIChatModel`` and ``OpenAIProvider`` are read off
    this module (not imported locally) so tests can patch them here.
    """
    openai_client = AsyncOpenAI(
        api_key="ollama",  # Ollama needs no auth; the client demands something
        base_url=f"{settings.ollama_base_url_effective}/v1",
    )
    # Ollama's OpenAI-compat endpoint silently DROPS the modern
    # ``max_completion_tokens`` field (only ``max_tokens`` maps to
    # num_predict), so route the cap to the legacy field or every
    # generation runs uncapped.
    from pydantic_ai.profiles.openai import OpenAIModelProfile

    return OpenAIChatModel(
        model_name=config.model,
        provider=OpenAIProvider(openai_client=openai_client),
        profile=OpenAIModelProfile(
            openai_chat_supports_max_completion_tokens=False
        ),
    )


def _openai_compatible(
    model_name: str, base_url: str, api_key: str | None, profile: Any = None
) -> Any:
    """A model on any server that speaks the OpenAI API.

    One client, pointed elsewhere. The key goes to the CLIENT rather than
    into ``OPENAI_API_KEY``, so a stack holding both a real OpenAI key
    and an aggregator's keeps them apart - stamping the environment would
    let whichever was built last answer for both.
    """
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    client = AsyncOpenAI(api_key=api_key or "none", base_url=base_url)
    kwargs: dict[str, Any] = {"provider": OpenAIProvider(openai_client=client)}
    if profile is not None:
        kwargs["profile"] = profile
    return OpenAIChatModel(model_name, **kwargs)


def _grant_kwargs(
    tools: Sequence[Any] = (),
    capabilities: Sequence[Any] = (),
    agent_name: str | None = None,
) -> dict[str, Any]:
    """Agent kwargs for an agent row's grants, omitted when empty so
    pydantic-ai versions without capability support never see the kwarg.
    The name rides along so traces carry ``gen_ai.agent.name``."""
    kwargs: dict[str, Any] = {}
    if tools:
        kwargs["tools"] = list(tools)
    if capabilities:
        kwargs["capabilities"] = list(capabilities)
    if agent_name:
        kwargs["name"] = agent_name
    return kwargs


def model_for(config: AIServiceConfig, settings: Any) -> tuple[Any, str]:
    """A bare model instance for ``config``, plus the model name it resolved to.

    ``get_agent`` wraps a whole ``Agent`` around this one. Callers that bring
    their own agent - chat_kit's ``ToolChatAgent``, headless jobs - need only
    the model, and have no way to reach one otherwise.

    Raises ``ProviderError`` for providers whose construction is not a plain
    model instance (the keyless public endpoints build their own clients); use
    ``get_agent`` for those.
    """
    if config.provider == AIProvider.OLLAMA:
        return _ollama_model(config, settings), config.model
    if config.provider in (AIProvider.PUBLIC, AIProvider.POLLINATIONS):
        raise ProviderError(
            f"model_for() does not support the {config.provider.value} provider; "
            "it builds its own client. Use get_agent() instead."
        )

    # PydanticAI 1.0+ reads credentials from the environment, not kwargs.
    os.environ[api_key_env(config.provider)] = require_api_key(config, settings)

    # An OpenAI-compatible provider is a base URL and a key, and the URL
    # is the only thing distinguishing Mistral, Cohere and OpenRouter
    # from OpenAI itself - so it rides the registry and they share a path.
    #
    # That path builds a client. ``OpenAIChatModel`` takes no
    # ``base_url``: passing one raises TypeError, which is what these two
    # branches did the moment anybody selected them.
    spec = PROVIDERS.get(config.provider)
    if spec is not None and spec.base_url:
        key = config.get_provider_config(settings).api_key
        return _openai_compatible(config.model, spec.base_url, key), config.model
    return _get_model_class(config.provider)(model_name=config.model), config.model


def validate_provider_support(provider: AIProvider) -> bool:
    """Check if a provider is supported in the current install.

    Catches ``ImportError`` (thrown lazily by pydantic-ai when an
    optional provider SDK isn't installed) in addition to our own
    ``ProviderError`` — a user who didn't select that provider via
    ``ai_providers`` at ``aegis init`` time has it effectively
    unsupported, not crashing.
    """
    try:
        _get_model_class(provider)
        return True
    except (ProviderError, ImportError):
        return False


def get_provider_model_class(provider: AIProvider):
    """Get the PydanticAI model class for a provider."""
    return _get_model_class(provider)
