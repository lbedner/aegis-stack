"""Tests for STT providers."""

from app.services.ai.domains.voice.models import STTProvider
from app.services.ai.domains.voice.stt import (
    BaseSTTProvider,
    FasterWhisperProvider,
    GroqWhisperProvider,
    OpenAIWhisperProvider,
    WhisperLocalProvider,
    get_stt_provider,
)


class TestGetSTTProvider:
    """Test get_stt_provider factory function."""

    def test_get_openai_whisper_provider(self) -> None:
        """Test factory returns OpenAIWhisperProvider."""
        provider = get_stt_provider(STTProvider.OPENAI_WHISPER)

        assert isinstance(provider, OpenAIWhisperProvider)
        assert provider.provider_type == STTProvider.OPENAI_WHISPER

    def test_get_whisper_local_provider(self) -> None:
        """Test factory returns WhisperLocalProvider."""
        provider = get_stt_provider(STTProvider.WHISPER_LOCAL)

        assert isinstance(provider, WhisperLocalProvider)
        assert provider.provider_type == STTProvider.WHISPER_LOCAL

    def test_get_faster_whisper_provider(self) -> None:
        """Test factory returns FasterWhisperProvider."""
        provider = get_stt_provider(STTProvider.FASTER_WHISPER)

        assert isinstance(provider, FasterWhisperProvider)
        assert provider.provider_type == STTProvider.FASTER_WHISPER

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

    def test_get_provider_with_kwargs(self) -> None:
        """Test factory passes kwargs to provider."""
        provider = get_stt_provider(
            STTProvider.OPENAI_WHISPER,
            base_url="https://custom.api.com",
        )

        assert isinstance(provider, OpenAIWhisperProvider)
        assert provider.base_url == "https://custom.api.com"


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


class TestWhisperLocalProvider:
    """Test WhisperLocalProvider class."""

    def test_default_model(self) -> None:
        """Test default model is openai/whisper-base."""
        provider = WhisperLocalProvider()

        assert provider.model_name == "openai/whisper-base"

    def test_custom_model(self) -> None:
        """Test custom model can be set."""
        provider = WhisperLocalProvider(model_name="openai/whisper-large-v3")

        assert provider.model_name == "openai/whisper-large-v3"

    def test_device_stored(self) -> None:
        """Test device is stored."""
        provider = WhisperLocalProvider(device="cuda")

        assert provider.device == "cuda"

    def test_device_default_none(self) -> None:
        """Test device defaults to None (auto-detect)."""
        provider = WhisperLocalProvider()

        assert provider.device is None

    def test_pipeline_lazy_loaded(self) -> None:
        """Test pipeline is not created until needed."""
        provider = WhisperLocalProvider()

        assert provider._pipeline is None

    def test_provider_type_is_local(self) -> None:
        """Test provider_type is WHISPER_LOCAL."""
        provider = WhisperLocalProvider()

        assert provider.provider_type == STTProvider.WHISPER_LOCAL


class TestFasterWhisperProvider:
    """Test FasterWhisperProvider class."""

    def test_default_model_size(self) -> None:
        """Test default model size is base."""
        provider = FasterWhisperProvider()

        assert provider.model_size == "base"

    def test_custom_model_size(self) -> None:
        """Test custom model size can be set."""
        provider = FasterWhisperProvider(model_size="large-v3")

        assert provider.model_size == "large-v3"

    def test_device_default(self) -> None:
        """Test device defaults to auto."""
        provider = FasterWhisperProvider()

        assert provider.device == "auto"

    def test_compute_type_default(self) -> None:
        """Test compute_type defaults to default."""
        provider = FasterWhisperProvider()

        assert provider.compute_type == "default"

    def test_custom_compute_type(self) -> None:
        """Test custom compute_type can be set."""
        provider = FasterWhisperProvider(compute_type="float16")

        assert provider.compute_type == "float16"

    def test_model_lazy_loaded(self) -> None:
        """Test model is not created until needed."""
        provider = FasterWhisperProvider()

        assert provider._model is None

    def test_provider_type_is_faster(self) -> None:
        """Test provider_type is FASTER_WHISPER."""
        provider = FasterWhisperProvider()

        assert provider.provider_type == STTProvider.FASTER_WHISPER


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
            WhisperLocalProvider,
            FasterWhisperProvider,
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
            (WhisperLocalProvider, STTProvider.WHISPER_LOCAL),
            (FasterWhisperProvider, STTProvider.FASTER_WHISPER),
            (GroqWhisperProvider, STTProvider.GROQ_WHISPER),
        ]

        for provider_class, expected_type in providers:
            assert hasattr(provider_class, "provider_type")
            assert provider_class.provider_type == expected_type
