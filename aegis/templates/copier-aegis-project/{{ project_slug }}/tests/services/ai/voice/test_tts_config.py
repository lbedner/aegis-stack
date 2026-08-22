"""Tests for TTS configuration."""

from unittest.mock import MagicMock

from app.services.ai.domains.voice.models import TTSProvider
from app.services.ai.domains.voice.tts import TTSConfig, get_tts_config


class TestTTSConfigDefaults:
    """Test TTSConfig default values."""

    def test_default_provider(self) -> None:
        """Test default provider is OpenAI."""
        config = TTSConfig()
        assert config.provider == TTSProvider.OPENAI

    def test_default_model_is_none(self) -> None:
        """Test default model is None (uses provider default)."""
        config = TTSConfig()
        assert config.model is None

    def test_default_voice_is_none(self) -> None:
        """Test default voice is None (uses provider default)."""
        config = TTSConfig()
        assert config.voice is None

    def test_default_speed_is_one(self) -> None:
        """Test default speed is 1.0."""
        config = TTSConfig()
        assert config.speed == 1.0


class TestTTSConfigFromSettings:
    """Test TTSConfig.from_settings() method."""

    def test_from_settings_with_all_values(self) -> None:
        """Test creating config from settings with all values set."""
        settings = MagicMock()
        settings.TTS_PROVIDER = "openai"
        settings.TTS_MODEL = "tts-1-hd"
        settings.TTS_VOICE = "nova"
        settings.TTS_SPEED = 1.5

        config = TTSConfig.from_settings(settings)

        assert config.provider == TTSProvider.OPENAI
        assert config.model == "tts-1-hd"
        assert config.voice == "nova"
        assert config.speed == 1.5

    def test_from_settings_with_missing_values(self) -> None:
        """Test creating config from settings with missing values uses defaults."""
        settings = MagicMock(spec=[])  # Empty spec means no attributes

        config = TTSConfig.from_settings(settings)

        assert config.provider == TTSProvider.OPENAI
        assert config.model is None
        assert config.voice is None
        assert config.speed == 1.0

    def test_from_settings_invalid_provider_falls_back(self) -> None:
        """Test invalid provider string falls back to OpenAI."""
        settings = MagicMock()
        settings.TTS_PROVIDER = "invalid_provider"
        settings.TTS_MODEL = None
        settings.TTS_VOICE = None
        settings.TTS_SPEED = 1.0

        config = TTSConfig.from_settings(settings)

        assert config.provider == TTSProvider.OPENAI

    def test_from_settings_each_provider(self) -> None:
        """Test each valid provider string is parsed correctly."""
        providers = [
            ("openai", TTSProvider.OPENAI),
        ]

        for provider_str, expected_enum in providers:
            settings = MagicMock()
            settings.TTS_PROVIDER = provider_str
            settings.TTS_MODEL = None
            settings.TTS_VOICE = None
            settings.TTS_SPEED = 1.0

            config = TTSConfig.from_settings(settings)
            assert config.provider == expected_enum, f"Failed for {provider_str}"


class TestTTSConfigGetModel:
    """Test TTSConfig.get_model() method."""

    def test_get_model_returns_explicit_model(self) -> None:
        """Test get_model returns explicit model when set."""
        config = TTSConfig(provider=TTSProvider.OPENAI, model="tts-1-hd")

        assert config.get_model() == "tts-1-hd"

    def test_get_model_returns_provider_default_openai(self) -> None:
        """Test get_model returns OpenAI default when model not set."""
        config = TTSConfig(provider=TTSProvider.OPENAI)

        assert config.get_model() == "tts-1"


class TestTTSConfigGetVoice:
    """Test TTSConfig.get_voice() method."""

    def test_get_voice_returns_explicit_voice(self) -> None:
        """Test get_voice returns explicit voice when set."""
        config = TTSConfig(provider=TTSProvider.OPENAI, voice="nova")

        assert config.get_voice() == "nova"

    def test_get_voice_returns_provider_default_openai(self) -> None:
        """Test get_voice returns OpenAI default when voice not set."""
        config = TTSConfig(provider=TTSProvider.OPENAI)

        assert config.get_voice() == "alloy"


class TestTTSConfigGetApiKey:
    """Test TTSConfig.get_api_key() method."""

    def test_get_api_key_openai(self) -> None:
        """Test get_api_key returns OpenAI key for OpenAI provider."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-openai-key"

        config = TTSConfig(provider=TTSProvider.OPENAI)

        assert config.get_api_key(settings) == "sk-test-openai-key"

    def test_get_api_key_missing_returns_none(self) -> None:
        """Test get_api_key returns None when key not set."""
        settings = MagicMock(spec=[])  # No attributes

        config = TTSConfig(provider=TTSProvider.OPENAI)

        assert config.get_api_key(settings) is None


class TestTTSConfigValidation:
    """Test TTSConfig.validate() method."""

    def test_validate_openai_with_key_passes(self) -> None:
        """Test validation passes when OpenAI key is set."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-key"

        config = TTSConfig(provider=TTSProvider.OPENAI)
        errors = config.validate(settings)

        assert len(errors) == 0

    def test_validate_openai_missing_key_fails(self) -> None:
        """Test validation fails when OpenAI key is missing."""
        settings = MagicMock(spec=[])

        config = TTSConfig(provider=TTSProvider.OPENAI)
        errors = config.validate(settings)

        assert len(errors) == 1
        assert "OPENAI_API_KEY" in errors[0]


class TestTTSConfigIsAvailable:
    """Test TTSConfig.is_available() method."""

    def test_is_available_true_when_valid(self) -> None:
        """Test is_available returns True when validation passes."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-key"

        config = TTSConfig(provider=TTSProvider.OPENAI)

        assert config.is_available(settings) is True

    def test_is_available_false_when_invalid(self) -> None:
        """Test is_available returns False when validation fails."""
        settings = MagicMock(spec=[])

        config = TTSConfig(provider=TTSProvider.OPENAI)

        assert config.is_available(settings) is False


class TestGetTTSConfigFunction:
    """Test get_tts_config() convenience function."""

    def test_get_tts_config_returns_tts_config(self) -> None:
        """Test get_tts_config returns TTSConfig instance."""
        settings = MagicMock()
        settings.TTS_PROVIDER = "openai"
        settings.TTS_MODEL = None
        settings.TTS_VOICE = None
        settings.TTS_SPEED = 1.0

        config = get_tts_config(settings)

        assert isinstance(config, TTSConfig)
        assert config.provider == TTSProvider.OPENAI
