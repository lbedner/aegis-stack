"""Tests for TTS providers."""

from app.services.ai.domains.voice.models import TTSProvider
from app.services.ai.domains.voice.tts import (
    BaseTTSProvider,
    OpenAITTSProvider,
    get_tts_provider,
)


class TestGetTTSProvider:
    """Test get_tts_provider factory function."""

    def test_get_openai_provider(self) -> None:
        """Test factory returns OpenAITTSProvider."""
        provider = get_tts_provider(TTSProvider.OPENAI)

        assert isinstance(provider, OpenAITTSProvider)
        assert provider.provider_type == TTSProvider.OPENAI

    def test_get_provider_with_api_key(self) -> None:
        """Test factory passes API key to provider."""
        provider = get_tts_provider(
            TTSProvider.OPENAI,
            api_key="sk-test-key",
        )

        assert isinstance(provider, OpenAITTSProvider)
        assert provider.api_key == "sk-test-key"

    def test_get_provider_with_model(self) -> None:
        """Test factory passes model to provider."""
        provider = get_tts_provider(
            TTSProvider.OPENAI,
            model="tts-1-hd",
        )

        assert isinstance(provider, OpenAITTSProvider)
        assert provider.model == "tts-1-hd"

    def test_get_provider_with_voice(self) -> None:
        """Test factory passes voice to provider."""
        provider = get_tts_provider(
            TTSProvider.OPENAI,
            voice="nova",
        )

        assert isinstance(provider, OpenAITTSProvider)
        assert provider.default_voice == "nova"

    def test_get_provider_with_kwargs(self) -> None:
        """Test factory passes kwargs to provider."""
        provider = get_tts_provider(
            TTSProvider.OPENAI,
            base_url="https://custom.api.com",
        )

        assert isinstance(provider, OpenAITTSProvider)
        assert provider.base_url == "https://custom.api.com"


class TestOpenAITTSProvider:
    """Test OpenAITTSProvider class."""

    def test_default_model(self) -> None:
        """Test default model is tts-1."""
        provider = OpenAITTSProvider()

        assert provider.model == "tts-1"

    def test_custom_model(self) -> None:
        """Test custom model can be set."""
        provider = OpenAITTSProvider(model="tts-1-hd")

        assert provider.model == "tts-1-hd"

    def test_default_voice(self) -> None:
        """Test default voice is alloy."""
        provider = OpenAITTSProvider()

        assert provider.default_voice == "alloy"

    def test_custom_voice(self) -> None:
        """Test custom voice can be set."""
        provider = OpenAITTSProvider(voice="nova")

        assert provider.default_voice == "nova"

    def test_api_key_stored(self) -> None:
        """Test API key is stored."""
        provider = OpenAITTSProvider(api_key="sk-test")

        assert provider.api_key == "sk-test"

    def test_base_url_stored(self) -> None:
        """Test base URL is stored."""
        provider = OpenAITTSProvider(base_url="https://custom.com")

        assert provider.base_url == "https://custom.com"

    def test_client_lazy_loaded(self) -> None:
        """Test client is not created until needed."""
        provider = OpenAITTSProvider()

        # Client should be None until _get_client is called
        assert provider._client is None

    def test_provider_type_is_openai(self) -> None:
        """Test provider_type is OPENAI."""
        provider = OpenAITTSProvider()

        assert provider.provider_type == TTSProvider.OPENAI

    def test_is_base_tts_provider(self) -> None:
        """Test inherits from BaseTTSProvider."""
        provider = OpenAITTSProvider()

        assert isinstance(provider, BaseTTSProvider)


class TestBaseTTSProviderInterface:
    """Test BaseTTSProvider abstract interface."""

    def test_all_providers_have_synthesize_method(self) -> None:
        """Test all provider classes have synthesize method."""
        providers = [
            OpenAITTSProvider,
        ]

        for provider_class in providers:
            assert hasattr(provider_class, "synthesize")
            # Method should be callable
            provider = provider_class()
            assert callable(provider.synthesize)

    def test_all_providers_have_synthesize_stream_method(self) -> None:
        """Test all provider classes have synthesize_stream method."""
        providers = [
            OpenAITTSProvider,
        ]

        for provider_class in providers:
            assert hasattr(provider_class, "synthesize_stream")
            # Method should be callable
            provider = provider_class()
            assert callable(provider.synthesize_stream)

    def test_all_providers_have_provider_type(self) -> None:
        """Test all provider classes have provider_type class attribute."""
        providers = [
            (OpenAITTSProvider, TTSProvider.OPENAI),
        ]

        for provider_class, expected_type in providers:
            assert hasattr(provider_class, "provider_type")
            assert provider_class.provider_type == expected_type
