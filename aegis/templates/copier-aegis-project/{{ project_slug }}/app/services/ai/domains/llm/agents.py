"""Building a PydanticAI agent: the four provider shapes."""

from typing import Any
from app.core.log import logger
from app.services.ai.config import AIServiceConfig, api_key_env
from app.services.ai.models import PROVIDERS, AIProvider
import json
from collections.abc import Sequence
import httpx
from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from app.services.ai.domains.llm.base import (
    ProviderError,
    ProviderNotInstalledError,
)
from app.services.ai.domains.llm.model_factory import (
    _grant_kwargs,
    _model_settings,
    _ollama_model,
    model_for,
)

def get_agent(
    config: AIServiceConfig,
    settings: Any,
    system_prompt_override: str | None = None,
    *,
    tools: Sequence[Any] = (),
    capabilities: Sequence[Any] = (),
    agent_name: str | None = None,
) -> Agent:
    """
    Create a PydanticAI Agent for the configured provider.

    Falls back to demo mode if no API keys are configured for immediate testing.

    Args:
        config: AI service configuration
        settings: Application settings for API keys
        system_prompt_override: Optional custom system prompt (for RAG mode)
        tools: Registry-resolved tools granted to the requesting agent row
        capabilities: pydantic-ai capabilities (e.g. code mode) for the row
        agent_name: Agent name stamped on traces (``gen_ai.agent.name``)

    Returns:
        Agent: Configured PydanticAI Agent

    Raises:
        ProviderError: If agent creation fails
    """
    try:
        # Special handling for PUBLIC provider (anonymous tier works keyless;
        # LLM7_API_KEY unlocks premium models)
        if config.provider == AIProvider.PUBLIC:
            return _create_public_agent(
                config,
                system_prompt_override,
                tools=tools,
                capabilities=capabilities,
                agent_name=agent_name,
            )

        # Special handling for POLLINATIONS provider (anonymous tier works
        # keyless; POLLINATIONS_API_KEY selects an account tier)
        if config.provider == AIProvider.POLLINATIONS:
            return _create_pollinations_agent(
                config,
                system_prompt_override,
                tools=tools,
                capabilities=capabilities,
                agent_name=agent_name,
            )

        # Special handling for OLLAMA provider (local, no API key required)
        if config.provider == AIProvider.OLLAMA:
            return _create_ollama_agent(
                config,
                settings,
                system_prompt_override,
                tools=tools,
                capabilities=capabilities,
                agent_name=agent_name,
            )

        # Key check, env-var handoff, and model construction all live in
        # ``model_for`` so agent-building and model-only callers cannot drift.
        model, _ = model_for(config, settings)

        # Determine system prompt
        system_prompt = system_prompt_override or (
            "You are a helpful AI assistant. Provide clear, accurate, "
            "and concise responses. Be friendly and professional."
        )

        # Create agent with system prompt, model settings, and grants
        agent = Agent(
            model=model,
            model_settings=_model_settings(config),
            system_prompt=system_prompt,
            **_grant_kwargs(tools, capabilities, agent_name),
        )

        return agent

    except Exception as e:
        error_str = str(e)
        # Check for missing dependency error (pydantic-ai pattern)
        if "Please install" in error_str and "to use the" in error_str:
            # Raise specific exception - CLI will handle display (no logging here)
            provider_name = config.provider.value.lower()
            raise ProviderNotInstalledError(
                provider=config.provider.value,
                cli_command=f"{{ project_slug }} ai add-provider {provider_name}",
            ) from e

        # Other errors still log and raise normally
        error_msg = f"Failed to create agent for {config.provider}: {e}"
        logger.error(error_msg)
        raise ProviderError(error_msg) from e


def _create_public_agent(
    config: AIServiceConfig,
    system_prompt_override: str | None = None,
    *,
    tools: Sequence[Any] = (),
    capabilities: Sequence[Any] = (),
    agent_name: str | None = None,
) -> Agent:
    """
    Create agent for PUBLIC provider using free public endpoints.

    Uses LLM7.io service which provides free access through an OpenAI-compatible API.

    Args:
        config: AI service configuration
        system_prompt_override: Optional custom system prompt (for RAG mode)
    """
    # Lazy imports - only needed for PUBLIC provider
    from openai import AsyncOpenAI

    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    try:
        # Create a custom HTTP client that fixes LLM7.io response format
        class FixedLLM7Client(httpx.AsyncClient):
            """Custom HTTP client that adds missing index field to LLM7.io responses."""

            async def send(self, request, **kwargs):
                response = await super().send(request, **kwargs)

                # If this is a chat completions request, fix the response
                if (
                    "/chat/completions" in str(request.url)
                    and request.method.upper() == "POST"
                ):
                    try:
                        # Check if this is a streaming response first
                        content_type = response.headers.get("content-type", "")
                        if (
                            "text/plain" in content_type
                            or "text/event-stream" in content_type
                            or "application/x-ndjson" in content_type
                        ):
                            return response

                        # Only process non-streaming JSON responses
                        if not response.headers.get("content-type", "").startswith(
                            "application/json"
                        ):
                            return response

                        # Get response text
                        response_text = response.text
                        data = json.loads(response_text)

                        # Add missing index field to choices
                        if "choices" in data and isinstance(data["choices"], list):
                            for i, choice in enumerate(data["choices"]):
                                if "index" not in choice or choice["index"] is None:
                                    choice["index"] = i

                        # Monkey patch the response to return fixed content
                        fixed_content = json.dumps(data)
                        response._content = fixed_content.encode()
                        response._text = fixed_content

                    except Exception as e:
                        logger.warning(f"Failed to fix LLM7.io response: {e}")

                return response

        # Create custom HTTP client
        custom_http_client = FixedLLM7Client()

        from .public_provider import LLM7_BASE_URL, public_api_key

        # Create the AsyncOpenAI client directly. LLM7.io requires a free
        # account key since mid-2026; public_api_key() warns when unset.
        openai_client = AsyncOpenAI(
            api_key=public_api_key(),
            base_url=LLM7_BASE_URL,
            http_client=custom_http_client,
        )

        # Create provider using the custom openai_client
        provider = OpenAIProvider(openai_client=openai_client)

        # Create OpenAI model using the provider. "auto" resolves against
        # LLM7's live catalog (their model list rotates).
        from .public_provider import resolve_public_model

        model_name = resolve_public_model(config.model)
        model = OpenAIChatModel(model_name=model_name, provider=provider)

        # Determine system prompt
        system_prompt = system_prompt_override or (
            "You are a helpful AI assistant powered by free public endpoints. "
            "Provide clear, accurate, and concise responses. "
            "Be friendly and professional."
        )

        # Create agent with system prompt, model settings, and grants
        agent = Agent(
            model=model,
            model_settings=_model_settings(config),
            system_prompt=system_prompt,
            **_grant_kwargs(tools, capabilities, agent_name),
        )

        return agent

    except Exception as e:
        error_msg = (
            f"Public endpoint failed ({e}). Here are reliable free alternatives:\n\n"
            "RECOMMENDED - Groq (Fastest, Most Generous Free Tier):\n"
            "   1. Visit: https://console.groq.com/keys\n"
            "   2. Get API key: export GROQ_API_KEY=your_key_here\n"
            "   3. Switch: {{ project_slug }} ai config set-provider groq\n\n"
            "Google AI Studio (Also Free):\n"
            "   1. Visit: https://aistudio.google.com/app/apikey\n"
            "   2. Get API key: export GOOGLE_API_KEY=your_key_here\n"
            "   3. Switch: {{ project_slug }} ai config set-provider google"
        )
        logger.error(f"Failed to create PUBLIC agent: {e}")
        raise ProviderError(error_msg) from e


def _create_pollinations_agent(
    config: AIServiceConfig,
    system_prompt_override: str | None = None,
    *,
    tools: Sequence[Any] = (),
    capabilities: Sequence[Any] = (),
    agent_name: str | None = None,
) -> Agent:
    """
    Create agent for the POLLINATIONS provider (keyless anonymous tier).

    Pollinations serves an OpenAI-compatible API; the anonymous tier
    needs no key but rejects ANY Authorization header, so keyless
    requests go through a client that strips it.

    Args:
        config: AI service configuration
        system_prompt_override: Optional custom system prompt (for RAG mode)
    """
    # Lazy imports - only needed for POLLINATIONS provider
    from openai import AsyncOpenAI

    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    from .pollinations_provider import (
        POLLINATIONS_BASE_URL,
        anonymous_async_http_client,
        pollinations_api_key,
        resolve_pollinations_model,
    )

    try:
        api_key = pollinations_api_key()
        if api_key:
            openai_client = AsyncOpenAI(
                api_key=api_key, base_url=POLLINATIONS_BASE_URL
            )
        else:
            # The SDK insists on a key; the anonymous client strips the
            # resulting header before it reaches the wire.
            openai_client = AsyncOpenAI(
                api_key="unused",
                base_url=POLLINATIONS_BASE_URL,
                http_client=anonymous_async_http_client(),
            )

        provider = OpenAIProvider(openai_client=openai_client)
        model_name = resolve_pollinations_model(config.model)
        model = OpenAIChatModel(model_name=model_name, provider=provider)

        system_prompt = system_prompt_override or (
            "You are a helpful AI assistant powered by free public endpoints. "
            "Provide clear, accurate, and concise responses. "
            "Be friendly and professional."
        )

        return Agent(
            model=model,
            model_settings=_model_settings(config),
            system_prompt=system_prompt,
            **_grant_kwargs(tools, capabilities, agent_name),
        )

    except Exception as e:
        error_msg = (
            f"Pollinations endpoint failed ({e}). The keyless 'public' provider "
            "(LLM7.io) is a drop-in alternative: "
            "{{ project_slug }} ai config set-provider public"
        )
        logger.error(f"Failed to create POLLINATIONS agent: {e}")
        raise ProviderError(error_msg) from e


def _create_ollama_agent(
    config: AIServiceConfig,
    settings: Any,
    system_prompt_override: str | None = None,
    *,
    tools: Sequence[Any] = (),
    capabilities: Sequence[Any] = (),
    agent_name: str | None = None,
) -> Agent:
    """
    Create agent for OLLAMA provider using local Ollama server.

    Uses Ollama's OpenAI-compatible API endpoint.

    Args:
        config: AI service configuration
        settings: Application settings for base URL
        system_prompt_override: Optional custom system prompt (for RAG mode)
    """
    try:
        model = _ollama_model(config, settings)

        # Determine system prompt
        system_prompt = system_prompt_override or (
            "You are a helpful AI assistant running locally via Ollama. "
            "Provide clear, accurate, and concise responses. "
            "Be friendly and professional."
        )

        # Create agent with system prompt, model settings, and grants
        agent = Agent(
            model=model,
            model_settings=_model_settings(config),
            system_prompt=system_prompt,
            **_grant_kwargs(tools, capabilities, agent_name),
        )

        return agent

    except Exception as e:
        error_msg = (
            f"Ollama connection failed ({e}).\n\n"
            "Make sure Ollama is running:\n"
            "   1. Install Ollama: https://ollama.com/download\n"
            "   2. Start Ollama: ollama serve\n"
            "   3. Pull a model: ollama pull llama3.2\n"
            "   4. Sync models: {{ project_slug }} llm sync --source=ollama\n\n"
            "If Ollama is running on a different host/port, set OLLAMA_BASE_URL in .env"
        )
        logger.error(f"Failed to create OLLAMA agent: {e}")
        raise ProviderError(error_msg) from e
