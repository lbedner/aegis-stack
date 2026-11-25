"""Building a PydanticAI model for a provider."""

from collections.abc import AsyncIterator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
import functools
import importlib
from typing import Any

import httpx
from openai import AsyncOpenAI
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestParameters, StreamedResponse
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.profiles.openai import openai_model_profile
from pydantic_ai.providers import infer_provider_class
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import RunContext

from app.core.config import settings as app_settings
from app.services.ai.domains.llm.base import (
    ProviderError,
    require_api_key,
)
from app.services.ai.domains.llm.config import AIServiceConfig
from app.services.ai.domains.llm.waiting import PrefillTee
from app.services.ai.models import PROVIDERS, AIProvider
from app.services.ai.models.provider_names import LOCAL_PROVIDERS, local_base_url


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


# Models that refused a temperature this process, learned from the refusal
# (``TemperatureTolerant``, which strips it from every request after): the
# profile below is the first answer, and this is what a model it gets wrong
# teaches.
# ponytail: per process - a restart relearns it at the cost of one refused
# request; persist it on the catalog row if that ever shows up in the logs.
_REJECTS_TEMPERATURE: set[str] = set()


def _bare_name(model: str) -> str:
    return model.split("/")[-1].lower()


def _supports_custom_temperature(model: str | None) -> bool:
    """Whether a model accepts a non-default ``temperature``.

    A model that reasons takes no sampling settings while it does, so the
    same rule pydantic-ai drops them by (with a warning each call) decides
    here, from the model's profile: one that reasons by default, or cannot
    turn reasoning off, takes the default (1) only. We never set an effort,
    so the default is what runs. One that has refused a temperature since
    this process started is never sent one (``TemperatureTolerant``),
    whatever this says.
    """
    if not model:
        return True
    profile = openai_model_profile(_bare_name(model))
    if not profile.get("openai_supports_reasoning", False):
        return True
    efforts = profile.get("openai_reasoning_efforts")
    can_stop = (
        "none" in efforts
        if efforts is not None
        else profile.get("openai_supports_reasoning_effort_none", False)
    )
    return can_stop and not profile.get("thinking_enabled_by_default", False)


def _sendable(model_name: str, settings: ModelSettings | None) -> ModelSettings | None:
    """``settings`` minus a temperature ``model_name`` has refused before:
    an agent built before the refusal still carries one."""
    if settings is None or _bare_name(model_name) not in _REJECTS_TEMPERATURE:
        return settings
    kept = settings.copy()
    kept.pop("temperature", None)
    return kept


def _refused_temperature(error: ModelHTTPError, settings: ModelSettings | None) -> bool:
    """A 400 whose complaint is the temperature this request carried."""
    return (
        error.status_code == 400
        and settings is not None
        and "temperature" in settings
        and "temperature" in str(error.body)
    )


class TemperatureTolerant(WrapperModel):
    """A model that, refused a temperature its profile said it takes,
    retries the request once without it and is never sent one again: a
    turn on a model the profile gets wrong still answers, instead of
    400ing every time. Every model an agent runs on is one (``model_for``,
    ``agents.get_agent``)."""

    def _learn(self, settings: ModelSettings | None) -> ModelSettings | None:
        _REJECTS_TEMPERATURE.add(_bare_name(self.model_name))
        return _sendable(self.model_name, settings)

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        settings = _sendable(self.model_name, model_settings)
        try:
            return await super().request(messages, settings, model_request_parameters)
        except ModelHTTPError as error:
            if not _refused_temperature(error, settings):
                raise
            return await super().request(
                messages, self._learn(settings), model_request_parameters
            )

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        # The refusal comes as the request opens, before anything streams,
        # so only the opening is retried - never a stream already under way.
        settings = _sendable(self.model_name, model_settings)
        async with AsyncExitStack() as stack:
            try:
                stream = await stack.enter_async_context(
                    super().request_stream(
                        messages, settings, model_request_parameters, run_context
                    )
                )
            except ModelHTTPError as error:
                if not _refused_temperature(error, settings):
                    raise
                stream = await stack.enter_async_context(
                    super().request_stream(
                        messages,
                        self._learn(settings),
                        model_request_parameters,
                        run_context,
                    )
                )
            yield stream


# A local model sends nothing until it has read the whole prompt: a 27B
# model at ~200 tokens a second takes over two minutes on a full 32k
# context, so the hosted models' timeout would cut every long turn mid-read.
LOCAL_TIMEOUT_SECONDS = 600.0


def _model_settings(config: Any) -> ModelSettings:
    """Build ModelSettings for the agent, omitting ``temperature`` for models
    that only accept the default so they don't 400 (see
    ``_supports_custom_temperature``)."""
    local = getattr(config, "provider", None) in LOCAL_PROVIDERS
    kwargs: dict[str, Any] = {
        "max_tokens": config.max_tokens,
        "timeout": LOCAL_TIMEOUT_SECONDS if local else config.timeout_seconds,
    }
    if _supports_custom_temperature(config.model):
        kwargs["temperature"] = config.temperature
    # llama-server alone reads these: how far it is through reading the
    # prompt, put into the stream (``waiting.PrefillTee``), and the cap on
    # a reply's thinking, which it writes no faster than the answer.
    if getattr(config, "provider", None) == AIProvider.LLAMACPP:
        extra: dict[str, Any] = {"return_progress": True}
        budget = getattr(app_settings, "LLAMACPP_THINKING_TOKENS", -1)
        if budget >= 0:
            extra["thinking_budget_tokens"] = budget
        kwargs["extra_body"] = extra
    # Effort is an Anthropic-only knob (thinking depth / token spend). Lazy
    # import mirrors ``_get_model_class``: the anthropic extra may not be
    # installed when another provider is configured.
    effort = getattr(config, "effort", None)
    if effort and getattr(config, "provider", None) == AIProvider.ANTHROPIC:
        from pydantic_ai.models.anthropic import AnthropicModelSettings

        return AnthropicModelSettings(anthropic_effort=effort, **kwargs)
    return ModelSettings(**kwargs)


@functools.cache
def _prefill_client() -> httpx.AsyncClient:
    """llama.cpp's one client, through ``PrefillTee``: built per turn, a
    client was never closed (openai's own closes itself; a plain one does
    not). ``PrefillTee`` reads the watching turn per request."""
    return httpx.AsyncClient(transport=PrefillTee())


def _local_model(config: AIServiceConfig, settings: Any) -> Any:
    """The model for a local server (Ollama, llama.cpp's llama-server),
    over its OpenAI-compatible API. Both stream reasoning in a field
    pydantic-ai reads (``reasoning``, ``reasoning_content``).

    ``AsyncOpenAI``, ``OpenAIChatModel`` and ``OpenAIProvider`` are read off
    this module (not imported locally) so tests can patch them here.
    """
    openai_client = AsyncOpenAI(
        api_key="local",  # neither needs auth; the client demands something
        base_url=local_base_url(config.provider, settings),
        # A retry would queue behind the abandoned request, still reading
        # the same prompt, and start reading it again after.
        max_retries=0,
        # llama-server says how far its prompt reading is, in the stream.
        http_client=(
            _prefill_client() if config.provider == AIProvider.LLAMACPP else None
        ),
    )
    # Ollama's OpenAI-compat endpoint silently DROPS the modern
    # ``max_completion_tokens`` field (only ``max_tokens`` maps to
    # num_predict), so route the cap to the legacy field or every
    # generation runs uncapped; llama-server takes it too.
    from pydantic_ai.profiles.openai import OpenAIModelProfile

    return OpenAIChatModel(
        model_name=config.model,
        provider=OpenAIProvider(openai_client=openai_client),
        profile=OpenAIModelProfile(openai_chat_supports_max_completion_tokens=False),
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


async def model_for(config: AIServiceConfig, settings: Any) -> tuple[Any, str]:
    """A bare model instance for ``config``, plus the model name it resolved to.

    ``get_agent`` wraps a whole ``Agent`` around this one. Callers that bring
    their own agent - chat_kit's ``ToolChatAgent``, headless jobs - need only
    the model, and have no way to reach one otherwise. Every one is
    ``TemperatureTolerant``: a temperature it refuses is retried without.

    Raises ``ProviderError`` for providers whose construction is not a plain
    model instance (the keyless public endpoints build their own clients); use
    ``get_agent`` for those.
    """
    return TemperatureTolerant(await _provider_model(config, settings)), config.model


async def _provider_model(config: AIServiceConfig, settings: Any) -> Any:
    """``model_for``'s model, before it learns to drop a temperature."""
    if config.provider in LOCAL_PROVIDERS:
        return _local_model(config, settings)
    if config.provider in (AIProvider.PUBLIC, AIProvider.POLLINATIONS):
        raise ProviderError(
            f"model_for() does not support the {config.provider.value} provider; "
            "it builds its own client. Use get_agent() instead."
        )

    # The key goes to the client, never into the environment: a key
    # stamped there outlives the call and answers for every later model.
    key = await require_api_key(config, settings)

    # An OpenAI-compatible provider is a base URL and a key, and the URL
    # is the only thing distinguishing Mistral, Cohere and OpenRouter
    # from OpenAI itself - so it rides the registry and they share a path.
    #
    # That path builds a client. ``OpenAIChatModel`` takes no
    # ``base_url``: passing one raises TypeError, which is what these two
    # branches did the moment anybody selected them.
    spec = PROVIDERS.get(config.provider)
    if spec is not None and spec.base_url:
        return _openai_compatible(config.model, spec.base_url, key)
    # Our provider names are pydantic-ai's, so it names the provider class
    # (typed as the bare base; every concrete one takes the key).
    provider_class: Any = infer_provider_class(config.provider.value)
    provider = provider_class(api_key=key)
    model_class = _get_model_class(config.provider)
    return model_class(config.model, provider=provider)


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
