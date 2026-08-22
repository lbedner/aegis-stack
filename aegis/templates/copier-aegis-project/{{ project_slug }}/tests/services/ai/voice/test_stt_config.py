"""Tests for STT configuration."""

from unittest.mock import MagicMock

from app.services.ai.domains.voice.models import STTProvider
from app.services.ai.domains.voice.stt import STTConfig, get_stt_config


class TestSTTConfigDefaults:
    """Test STTConfig default values."""

    def test_default_provider(self) -> None:
        """Test default provider is OpenAI Whisper."""
        config = STTConfig()
        assert config.provider == STTProvider.OPENAI_WHISPER

    def test_default_model_is_none(self) -> None:
        """Test default model is None (uses provider default)."""
        config = STTConfig()
        assert config.model is None

    def test_default_language_is_none(self) -> None:
        """Test default language is None (auto-detect)."""
        config = STTConfig()
        assert config.language is None

    def test_default_device_is_none(self) -> None:
        """Test default device is None (auto-detect for local providers)."""
        config = STTConfig()
        assert config.device is None


class TestSTTConfigFromSettings:
    """Test STTConfig.from_settings() method."""

    def test_from_settings_with_all_values(self) -> None:
        """Test creating config from settings with all values set."""
        settings = MagicMock()
        settings.STT_PROVIDER = "groq_whisper"
        settings.STT_MODEL = "whisper-large-v3"
        settings.STT_LANGUAGE = "en"
        settings.STT_DEVICE = "cuda"

        config = STTConfig.from_settings(settings)

        assert config.provider == STTProvider.GROQ_WHISPER
        assert config.model == "whisper-large-v3"
        assert config.language == "en"
        assert config.device == "cuda"

    def test_from_settings_with_missing_values(self) -> None:
        """Test creating config from settings with missing values uses defaults."""
        settings = MagicMock(spec=[])  # Empty spec means no attributes

        config = STTConfig.from_settings(settings)

        assert config.provider == STTProvider.OPENAI_WHISPER
        assert config.model is None
        assert config.language is None
        assert config.device is None

    def test_from_settings_invalid_provider_falls_back(self) -> None:
        """Test invalid provider string falls back to OpenAI Whisper."""
        settings = MagicMock()
        settings.STT_PROVIDER = "invalid_provider"
        settings.STT_MODEL = None
        settings.STT_LANGUAGE = None
        settings.STT_DEVICE = None

        config = STTConfig.from_settings(settings)

        assert config.provider == STTProvider.OPENAI_WHISPER

    def test_from_settings_each_provider(self) -> None:
        """Test each valid provider string is parsed correctly."""
        providers = [
            ("openai_whisper", STTProvider.OPENAI_WHISPER),
            ("groq_whisper", STTProvider.GROQ_WHISPER),
            ("whisper_local", STTProvider.WHISPER_LOCAL),
            ("faster_whisper", STTProvider.FASTER_WHISPER),
        ]

        for provider_str, expected_enum in providers:
            settings = MagicMock()
            settings.STT_PROVIDER = provider_str
            settings.STT_MODEL = None
            settings.STT_LANGUAGE = None
            settings.STT_DEVICE = None

            config = STTConfig.from_settings(settings)
            assert config.provider == expected_enum, f"Failed for {provider_str}"


class TestSTTConfigGetModel:
    """Test STTConfig.get_model() method."""

    def test_get_model_returns_explicit_model(self) -> None:
        """Test get_model returns explicit model when set."""
        config = STTConfig(provider=STTProvider.OPENAI_WHISPER, model="custom-model")

        assert config.get_model() == "custom-model"

    def test_get_model_returns_provider_default_openai(self) -> None:
        """Test get_model returns OpenAI default when model not set."""
        config = STTConfig(provider=STTProvider.OPENAI_WHISPER)

        assert config.get_model() == "whisper-1"

    def test_get_model_returns_provider_default_groq(self) -> None:
        """Test get_model returns Groq default when model not set."""
        config = STTConfig(provider=STTProvider.GROQ_WHISPER)

        assert config.get_model() == "whisper-large-v3-turbo"

    def test_get_model_returns_provider_default_local(self) -> None:
        """Test get_model returns local Whisper default when model not set."""
        config = STTConfig(provider=STTProvider.WHISPER_LOCAL)

        assert config.get_model() == "openai/whisper-base"

    def test_get_model_returns_provider_default_faster(self) -> None:
        """Test get_model returns faster-whisper default when model not set."""
        config = STTConfig(provider=STTProvider.FASTER_WHISPER)

        assert config.get_model() == "base"


class TestSTTConfigGetApiKey:
    """Test STTConfig.get_api_key() method."""

    def test_get_api_key_openai(self) -> None:
        """Test get_api_key returns OpenAI key for OpenAI provider."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-openai-key"

        config = STTConfig(provider=STTProvider.OPENAI_WHISPER)

        assert config.get_api_key(settings) == "sk-test-openai-key"

    def test_get_api_key_groq(self) -> None:
        """Test get_api_key returns Groq key for Groq provider."""
        settings = MagicMock()
        settings.GROQ_API_KEY = "gsk-test-groq-key"

        config = STTConfig(provider=STTProvider.GROQ_WHISPER)

        assert config.get_api_key(settings) == "gsk-test-groq-key"

    def test_get_api_key_local_returns_none(self) -> None:
        """Test get_api_key returns None for local providers."""
        settings = MagicMock()

        config = STTConfig(provider=STTProvider.WHISPER_LOCAL)

        assert config.get_api_key(settings) is None

    def test_get_api_key_faster_whisper_returns_none(self) -> None:
        """Test get_api_key returns None for faster-whisper."""
        settings = MagicMock()

        config = STTConfig(provider=STTProvider.FASTER_WHISPER)

        assert config.get_api_key(settings) is None

    def test_get_api_key_missing_returns_none(self) -> None:
        """Test get_api_key returns None when key not set."""
        settings = MagicMock(spec=[])  # No attributes

        config = STTConfig(provider=STTProvider.OPENAI_WHISPER)

        assert config.get_api_key(settings) is None


class TestSTTConfigValidation:
    """Test STTConfig.validate() method."""

    def test_validate_openai_with_key_passes(self) -> None:
        """Test validation passes when OpenAI key is set."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-key"

        config = STTConfig(provider=STTProvider.OPENAI_WHISPER)
        errors = config.validate(settings)

        assert len(errors) == 0

    def test_validate_openai_missing_key_fails(self) -> None:
        """Test validation fails when OpenAI key is missing."""
        settings = MagicMock(spec=[])

        config = STTConfig(provider=STTProvider.OPENAI_WHISPER)
        errors = config.validate(settings)

        assert len(errors) == 1
        assert "OPENAI_API_KEY" in errors[0]

    def test_validate_groq_with_key_passes(self) -> None:
        """Test validation passes when Groq key is set."""
        settings = MagicMock()
        settings.GROQ_API_KEY = "gsk-test-key"

        config = STTConfig(provider=STTProvider.GROQ_WHISPER)
        errors = config.validate(settings)

        assert len(errors) == 0

    def test_validate_groq_missing_key_fails(self) -> None:
        """Test validation fails when Groq key is missing."""
        settings = MagicMock(spec=[])

        config = STTConfig(provider=STTProvider.GROQ_WHISPER)
        errors = config.validate(settings)

        assert len(errors) == 1
        assert "GROQ_API_KEY" in errors[0]

    def test_validate_local_no_key_required(self) -> None:
        """Test validation passes for local providers without API key."""
        settings = MagicMock(spec=[])

        config = STTConfig(provider=STTProvider.WHISPER_LOCAL)
        errors = config.validate(settings)

        assert len(errors) == 0

    def test_validate_faster_whisper_no_key_required(self) -> None:
        """Test validation passes for faster-whisper without API key."""
        settings = MagicMock(spec=[])

        config = STTConfig(provider=STTProvider.FASTER_WHISPER)
        errors = config.validate(settings)

        assert len(errors) == 0

    def test_validate_invalid_language_code_fails(self) -> None:
        """Test validation fails for invalid language code format."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-key"

        config = STTConfig(provider=STTProvider.OPENAI_WHISPER, language="english")
        errors = config.validate(settings)

        assert len(errors) == 1
        assert "language code" in errors[0].lower()

    def test_validate_valid_language_code_passes(self) -> None:
        """Test validation passes for valid ISO 639-1 language code."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-key"

        config = STTConfig(provider=STTProvider.OPENAI_WHISPER, language="en")
        errors = config.validate(settings)

        assert len(errors) == 0

    def test_validate_multiple_errors(self) -> None:
        """Test validation can return multiple errors."""
        settings = MagicMock(spec=[])

        config = STTConfig(provider=STTProvider.OPENAI_WHISPER, language="invalid")
        errors = config.validate(settings)

        assert len(errors) == 2  # Missing API key + invalid language


class TestSTTConfigIsAvailable:
    """Test STTConfig.is_available() method."""

    def test_is_available_true_when_valid(self) -> None:
        """Test is_available returns True when validation passes."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-key"

        config = STTConfig(provider=STTProvider.OPENAI_WHISPER)

        assert config.is_available(settings) is True

    def test_is_available_false_when_invalid(self) -> None:
        """Test is_available returns False when validation fails."""
        settings = MagicMock(spec=[])

        config = STTConfig(provider=STTProvider.OPENAI_WHISPER)

        assert config.is_available(settings) is False


class TestGetSTTConfigFunction:
    """Test get_stt_config() convenience function."""

    def test_get_stt_config_returns_stt_config(self) -> None:
        """Test get_stt_config returns STTConfig instance."""
        settings = MagicMock()
        settings.STT_PROVIDER = "openai_whisper"
        settings.STT_MODEL = None
        settings.STT_LANGUAGE = None
        settings.STT_DEVICE = None

        config = get_stt_config(settings)

        assert isinstance(config, STTConfig)
        assert config.provider == STTProvider.OPENAI_WHISPER
