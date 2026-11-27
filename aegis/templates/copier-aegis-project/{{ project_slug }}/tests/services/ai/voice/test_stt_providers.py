"""Tests for STT providers."""

from app.services.ai.domains.voice.models import STTProvider
from app.services.ai.domains.voice.stt import (
    BaseSTTProvider,
    GroqWhisperProvider,
    OpenAIWhisperProvider,
    get_stt_provider,
)


class TestGetSTTProvider:
    """Test get_stt_provider factory function."""

    def test_get_openai_whisper_provider(self) -> None:
        """Test factory returns OpenAIWhisperProvider."""
        provider = get_stt_provider(STTProvider.OPENAI_WHISPER)

        assert isinstance(provider, OpenAIWhisperProvider)
        assert provider.provider_type == STTProvider.OPENAI_WHISPER

    def test_get_groq_whisper_provider(self) -> None:
        """Test factory returns GroqWhisperProvider."""
        provider = get_stt_provider(STTProvider.GROQ_WHISPER)

        assert isinstance(provider, GroqWhisperProvider)
        assert provider.provider_type == STTProvider.GROQ_WHISPER

    def test_get_provider_with_api_key(self) -> None:
        """Test factory passes API key to provider."""
        provider = get_stt_provider(
            STTProvider.OPENAI_WHISPER,
            api_key="sk-test-key",
        )

        assert isinstance(provider, OpenAIWhisperProvider)
        assert provider.api_key == "sk-test-key"

    def test_get_provider_with_model(self) -> None:
        """Test factory passes model to provider."""
        provider = get_stt_provider(
            STTProvider.OPENAI_WHISPER,
            model="whisper-large",
        )

        assert isinstance(provider, OpenAIWhisperProvider)
        assert provider.model == "whisper-large"


class TestOpenAIWhisperProvider:
    """Test OpenAIWhisperProvider class."""

    def test_default_model(self) -> None:
        """Test default model is whisper-1."""
        provider = OpenAIWhisperProvider()

        assert provider.model == "whisper-1"

    def test_custom_model(self) -> None:
        """Test custom model can be set."""
        provider = OpenAIWhisperProvider(model="whisper-large")

        assert provider.model == "whisper-large"

    def test_api_key_stored(self) -> None:
        """Test API key is stored."""
        provider = OpenAIWhisperProvider(api_key="sk-test")

        assert provider.api_key == "sk-test"

    def test_base_url_stored(self) -> None:
        """Test base URL is stored."""
        provider = OpenAIWhisperProvider(base_url="https://custom.com")

        assert provider.base_url == "https://custom.com"

    def test_client_lazy_loaded(self) -> None:
        """Test client is not created until needed."""
        provider = OpenAIWhisperProvider()

        # Client should be None until _get_client is called
        assert provider._client is None

    def test_provider_type_is_openai(self) -> None:
        """Test provider_type is OPENAI_WHISPER."""
        provider = OpenAIWhisperProvider()

        assert provider.provider_type == STTProvider.OPENAI_WHISPER

    def test_is_base_stt_provider(self) -> None:
        """Test inherits from BaseSTTProvider."""
        provider = OpenAIWhisperProvider()

        assert isinstance(provider, BaseSTTProvider)


class TestGroqWhisperProvider:
    """Test GroqWhisperProvider class."""

    def test_default_model(self) -> None:
        """Test default model is whisper-large-v3-turbo."""
        provider = GroqWhisperProvider()

        assert provider.model == "whisper-large-v3-turbo"

    def test_custom_model(self) -> None:
        """Test custom model can be set."""
        provider = GroqWhisperProvider(model="whisper-large-v3")

        assert provider.model == "whisper-large-v3"

    def test_api_key_stored(self) -> None:
        """Test API key is stored."""
        provider = GroqWhisperProvider(api_key="gsk-test")

        assert provider.api_key == "gsk-test"

    def test_client_lazy_loaded(self) -> None:
        """Test client is not created until needed."""
        provider = GroqWhisperProvider()

        assert provider._client is None

    def test_provider_type_is_groq(self) -> None:
        """Test provider_type is GROQ_WHISPER."""
        provider = GroqWhisperProvider()

        assert provider.provider_type == STTProvider.GROQ_WHISPER


class TestBaseSTTProviderInterface:
    """Test BaseSTTProvider abstract interface."""

    def test_all_providers_have_transcribe_method(self) -> None:
        """Test all provider classes have transcribe method."""
        providers = [
            OpenAIWhisperProvider,
            GroqWhisperProvider,
        ]

        for provider_class in providers:
            assert hasattr(provider_class, "transcribe")
            # Method should be callable
            provider = provider_class()
            assert callable(provider.transcribe)

    def test_all_providers_have_provider_type(self) -> None:
        """Test all provider classes have provider_type class attribute."""
        providers = [
            (OpenAIWhisperProvider, STTProvider.OPENAI_WHISPER),
            (GroqWhisperProvider, STTProvider.GROQ_WHISPER),
        ]

        for provider_class, expected_type in providers:
            assert hasattr(provider_class, "provider_type")
            assert provider_class.provider_type == expected_type


class TestOpenAIResponseFormat:
    """Only Whisper answers ``verbose_json``; the gpt-4o transcription
    models accept ``json``/``text`` and reject every call otherwise."""

    async def _format_sent(self, model: str) -> str:
        from unittest.mock import AsyncMock, MagicMock

        from app.services.ai.domains.voice.models import AudioInput

        provider = OpenAIWhisperProvider(model=model)
        reply = MagicMock(text="hi", segments=None, language=None, duration=None)
        create = AsyncMock(return_value=reply)
        provider._client = MagicMock()
        provider._client.audio.transcriptions.create = create
        await provider.transcribe(AudioInput(content=b"x"))
        return create.call_args.kwargs["response_format"]

    async def test_whisper_gets_verbose_json(self) -> None:
        assert await self._format_sent("whisper-1") == "verbose_json"

    async def test_gpt_4o_models_get_json(self) -> None:
        assert await self._format_sent("gpt-4o-mini-transcribe") == "json"
        assert await self._format_sent("gpt-4o-transcribe") == "json"

    async def test_a_hint_rides_as_the_prompt(self) -> None:
        """Names the model cannot guess go to it as the API's ``prompt``."""
        from unittest.mock import AsyncMock, MagicMock

        from app.services.ai.domains.voice.models import AudioInput

        provider = OpenAIWhisperProvider(model="gpt-4o-mini-transcribe")
        reply = MagicMock(text="hi", segments=None, language=None, duration=None)
        create = AsyncMock(return_value=reply)
        provider._client = MagicMock()
        provider._client.audio.transcriptions.create = create

        await provider.transcribe(AudioInput(content=b"x", prompt="Illiana"))
        assert create.call_args.kwargs["prompt"] == "Illiana"

        await provider.transcribe(AudioInput(content=b"x"))
        assert "prompt" not in create.call_args.kwargs
