"""Tests for AI provider factory including Ollama support."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.ai.models import AIProvider
from app.services.ai.providers import (
    ProviderError,
    _get_model_class,
    get_agent,
    get_supported_providers,
    validate_provider_support,
)

# =============================================================================
# TestGetModelClass
# =============================================================================


class TestGetModelClass:
    """Tests for provider model class selection.

    Each provider-specific test skips itself if the underlying SDK isn't
    installed — generated projects only pull in the SDKs for providers
    the user selected via ``ai_providers`` (default: ``openai``).
    Running ``test_anthropic_returns_anthropic_model`` in an openai-only
    project would otherwise surface as an ``ImportError`` from
    pydantic-ai's dynamic provider imports rather than a skip.
    """

    def test_ollama_returns_openai_model(self) -> None:
        """Verify Ollama provider uses OpenAIChatModel."""
        pytest.importorskip("openai")
        model_class = _get_model_class(AIProvider.OLLAMA)
        # Ollama uses OpenAI-compatible API, so it should return OpenAIChatModel
        assert model_class.__name__ == "OpenAIChatModel"

    def test_openai_returns_openai_model(self) -> None:
        """Verify OpenAI provider uses OpenAIChatModel."""
        pytest.importorskip("openai")
        model_class = _get_model_class(AIProvider.OPENAI)
        assert model_class.__name__ == "OpenAIChatModel"

    def test_anthropic_returns_anthropic_model(self) -> None:
        """Verify Anthropic provider uses AnthropicModel."""
        pytest.importorskip("anthropic")
        model_class = _get_model_class(AIProvider.ANTHROPIC)
        assert model_class.__name__ == "AnthropicModel"

    def test_google_returns_google_model(self) -> None:
        """Verify Google provider uses GoogleModel."""
        pytest.importorskip("google.genai")
        model_class = _get_model_class(AIProvider.GOOGLE)
        assert model_class.__name__ == "GoogleModel"

    def test_groq_returns_groq_model(self) -> None:
        """Verify Groq provider uses GroqModel."""
        pytest.importorskip("groq")
        model_class = _get_model_class(AIProvider.GROQ)
        assert model_class.__name__ == "GroqModel"

    def test_mistral_returns_openai_model(self) -> None:
        """Verify Mistral provider uses OpenAIChatModel (OpenAI-compatible)."""
        pytest.importorskip("openai")
        model_class = _get_model_class(AIProvider.MISTRAL)
        assert model_class.__name__ == "OpenAIChatModel"

    def test_cohere_returns_openai_model(self) -> None:
        """Verify Cohere provider uses OpenAIChatModel (OpenAI-compatible)."""
        pytest.importorskip("openai")
        model_class = _get_model_class(AIProvider.COHERE)
        assert model_class.__name__ == "OpenAIChatModel"

    def test_public_returns_openai_model(self) -> None:
        """Verify Public provider uses OpenAIChatModel."""
        pytest.importorskip("openai")
        model_class = _get_model_class(AIProvider.PUBLIC)
        assert model_class.__name__ == "OpenAIChatModel"

    def test_pollinations_returns_openai_model(self) -> None:
        """Verify Pollinations provider uses OpenAIChatModel (OpenAI-compatible)."""
        pytest.importorskip("openai")
        model_class = _get_model_class(AIProvider.POLLINATIONS)
        assert model_class.__name__ == "OpenAIChatModel"


# =============================================================================
# TestValidateProviderSupport
# =============================================================================


class TestValidateProviderSupport:
    """Tests for provider validation."""

    def test_ollama_is_supported(self) -> None:
        """Verify Ollama is a supported provider."""
        # Ollama routes through pydantic-ai's OpenAI model, which needs the
        # openai SDK — only installed when an OpenAI-compatible provider was
        # selected at generation time.
        pytest.importorskip("openai")
        assert validate_provider_support(AIProvider.OLLAMA) is True

    def test_all_standard_providers_supported(self) -> None:
        """Verify all standard providers with available SDKs are supported.

        Generated projects only pull in the SDKs for providers the user
        selected via ``ai_providers`` (default: ``openai``). Anthropic,
        Google, Groq etc. are lazy-imported inside pydantic-ai; asking
        for their model class without the SDK raises ``ImportError``.
        This test checks only the always-available providers plus any
        whose SDK is actually installed in the current env.
        """
        # The OpenAI-compatible providers below all resolve through
        # pydantic-ai's OpenAI model, which needs the openai SDK. That SDK is
        # only installed when an OpenAI-compatible provider was selected at
        # generation time (e.g. not in an anthropic-only build).
        pytest.importorskip("openai")
        # Always-available (no extra SDK needed beyond openai-compatible):
        always_available = [
            AIProvider.OPENAI,
            AIProvider.MISTRAL,
            AIProvider.COHERE,
            AIProvider.OLLAMA,
            AIProvider.PUBLIC,
        ]
        for provider in always_available:
            assert validate_provider_support(provider) is True

        # Optional providers: check only when their SDK is installed.
        optional = {
            "anthropic": AIProvider.ANTHROPIC,
            "google.genai": AIProvider.GOOGLE,
            "groq": AIProvider.GROQ,
        }
        for module_name, provider in optional.items():
            try:
                __import__(module_name)
            except ImportError:
                continue
            assert validate_provider_support(provider) is True


# =============================================================================
# TestGetSupportedProviders
# =============================================================================


class TestGetSupportedProviders:
    """Tests for getting list of supported providers."""

    def test_ollama_in_supported_providers(self) -> None:
        """Verify Ollama is in the list of supported providers."""
        providers = get_supported_providers()
        assert AIProvider.OLLAMA in providers

    def test_supported_providers_count(self) -> None:
        """Verify expected number of supported providers."""
        providers = get_supported_providers()
        # Should have at least 8 providers: openai, anthropic, google,
        # groq, mistral, cohere, ollama, public
        assert len(providers) >= 8

    def test_public_in_supported_providers(self) -> None:
        """Verify PUBLIC is in the list of supported providers."""
        providers = get_supported_providers()
        assert AIProvider.PUBLIC in providers

    def test_pollinations_in_supported_providers(self) -> None:
        """Verify POLLINATIONS is in the list of supported providers."""
        providers = get_supported_providers()
        assert AIProvider.POLLINATIONS in providers


# =============================================================================
# TestGetAgentOllama
# =============================================================================


class TestGetAgentOllama:
    """Tests for agent creation with Ollama provider."""

    @patch("app.services.ai.providers.AsyncOpenAI")
    @patch("app.services.ai.providers.OpenAIProvider")
    @patch("app.services.ai.providers.OpenAIChatModel")
    @patch("app.services.ai.providers.Agent")
    def test_get_agent_ollama_creates_agent(
        self,
        mock_agent_class: MagicMock,
        mock_model_class: MagicMock,
        mock_provider_class: MagicMock,
        mock_openai_class: MagicMock,
    ) -> None:
        """Verify agent is created successfully for Ollama provider."""
        # Setup mocks
        mock_settings = MagicMock()
        mock_settings.ollama_base_url_effective = "http://localhost:11434"

        mock_config = MagicMock()
        mock_config.provider = AIProvider.OLLAMA
        mock_config.model = "llama3.2:latest"
        mock_config.temperature = 0.7
        mock_config.max_tokens = 4096
        mock_config.timeout_seconds = 120.0

        mock_agent_instance = MagicMock()
        mock_agent_class.return_value = mock_agent_instance

        # Call get_agent
        result = get_agent(mock_config, mock_settings)

        # Verify OpenAI client was created with Ollama base URL
        mock_openai_class.assert_called_once()
        call_kwargs = mock_openai_class.call_args[1]
        assert call_kwargs["base_url"] == "http://localhost:11434/v1"
        assert call_kwargs["api_key"] == "ollama"

        # Verify agent was created
        assert result == mock_agent_instance

    @patch("app.services.ai.providers.AsyncOpenAI")
    @patch("app.services.ai.providers.OpenAIProvider")
    @patch("app.services.ai.providers.OpenAIChatModel")
    @patch("app.services.ai.providers.Agent")
    def test_get_agent_ollama_uses_model_name(
        self,
        mock_agent_class: MagicMock,
        mock_model_class: MagicMock,
        mock_provider_class: MagicMock,
        mock_openai_class: MagicMock,
    ) -> None:
        """Verify agent uses the correct model name from config."""
        mock_settings = MagicMock()
        mock_settings.ollama_base_url_effective = "http://localhost:11434"

        mock_config = MagicMock()
        mock_config.provider = AIProvider.OLLAMA
        mock_config.model = "mistral:7b"
        mock_config.temperature = 0.7
        mock_config.max_tokens = 4096
        mock_config.timeout_seconds = 120.0

        get_agent(mock_config, mock_settings)

        # Verify model was created with correct model name
        mock_model_class.assert_called_once()
        call_kwargs = mock_model_class.call_args[1]
        assert call_kwargs["model_name"] == "mistral:7b"

    @patch("app.services.ai.providers.AsyncOpenAI")
    def test_get_agent_ollama_connection_error(
        self,
        mock_openai_class: MagicMock,
    ) -> None:
        """Verify helpful error message when Ollama connection fails."""
        mock_openai_class.side_effect = Exception("Connection refused")

        mock_settings = MagicMock()
        mock_settings.ollama_base_url_effective = "http://localhost:11434"

        mock_config = MagicMock()
        mock_config.provider = AIProvider.OLLAMA
        mock_config.model = "llama3.2:latest"
        mock_config.temperature = 0.7
        mock_config.max_tokens = 4096
        mock_config.timeout_seconds = 120.0

        with pytest.raises(ProviderError) as exc_info:
            get_agent(mock_config, mock_settings)

        error_msg = str(exc_info.value)
        # Should include helpful instructions
        assert "Ollama" in error_msg
        assert "ollama serve" in error_msg or "running" in error_msg.lower()


# =============================================================================
# TestOllamaBaseUrlConfiguration
# =============================================================================


class TestOllamaBaseUrlConfiguration:
    """Tests for Ollama base URL configuration."""

    @patch("app.services.ai.providers.AsyncOpenAI")
    @patch("app.services.ai.providers.OpenAIProvider")
    @patch("app.services.ai.providers.OpenAIChatModel")
    @patch("app.services.ai.providers.Agent")
    def test_ollama_uses_effective_base_url(
        self,
        mock_agent_class: MagicMock,
        mock_model_class: MagicMock,
        mock_provider_class: MagicMock,
        mock_openai_class: MagicMock,
    ) -> None:
        """Verify Ollama uses ollama_base_url_effective from settings."""
        mock_settings = MagicMock()
        # Custom base URL for Docker or remote Ollama
        mock_settings.ollama_base_url_effective = "http://ollama-server:11434"

        mock_config = MagicMock()
        mock_config.provider = AIProvider.OLLAMA
        mock_config.model = "llama3.2:latest"
        mock_config.temperature = 0.7
        mock_config.max_tokens = 4096
        mock_config.timeout_seconds = 120.0

        get_agent(mock_config, mock_settings)

        # Verify custom base URL was used with /v1 suffix
        mock_openai_class.assert_called_once()
        call_kwargs = mock_openai_class.call_args[1]
        assert call_kwargs["base_url"] == "http://ollama-server:11434/v1"
