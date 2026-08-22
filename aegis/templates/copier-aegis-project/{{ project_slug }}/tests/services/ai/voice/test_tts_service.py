"""Tests for TTS service."""

from unittest.mock import MagicMock

from app.services.ai.domains.voice.models import TTSProvider
from app.services.ai.domains.voice.tts import TTSService


class TestTTSServiceInit:
    """Test TTSService initialization."""

    def test_init_with_settings(self) -> None:
        """Test initialization with settings object."""
        settings = MagicMock()
        settings.TTS_PROVIDER = "openai"
        settings.TTS_MODEL = "tts-1-hd"
        settings.TTS_VOICE = "nova"
        settings.TTS_SPEED = 1.5

        service = TTSService(settings)

        assert service.provider_type == TTSProvider.OPENAI
        assert service.model == "tts-1-hd"
        assert service.voice == "nova"

    def test_init_with_explicit_provider(self) -> None:
        """Test initialization with explicit provider overrides settings."""
        settings = MagicMock()
        settings.TTS_PROVIDER = "openai"

        service = TTSService(settings, provider=TTSProvider.OPENAI)

        assert service.provider_type == TTSProvider.OPENAI

    def test_init_with_explicit_model(self) -> None:
        """Test initialization with explicit model overrides settings."""
        settings = MagicMock()
        settings.TTS_MODEL = "tts-1"

        service = TTSService(settings, model="tts-1-hd")

        assert service.model == "tts-1-hd"

    def test_init_with_explicit_voice(self) -> None:
        """Test initialization with explicit voice overrides settings."""
        settings = MagicMock()
        settings.TTS_VOICE = "alloy"

        service = TTSService(settings, voice="nova")

        assert service.voice == "nova"

    def test_init_without_settings(self) -> None:
        """Test initialization without settings uses defaults."""
        service = TTSService()

        assert service.provider_type == TTSProvider.OPENAI
        assert service.model == "tts-1"
        assert service.voice == "alloy"


class TestTTSServiceProperties:
    """Test TTSService properties."""

    def test_config_property(self) -> None:
        """Test config property returns TTSConfig."""
        service = TTSService()

        config = service.config

        assert config.provider == TTSProvider.OPENAI

    def test_provider_type_property(self) -> None:
        """Test provider_type property."""
        service = TTSService(provider=TTSProvider.OPENAI)

        assert service.provider_type == TTSProvider.OPENAI

    def test_model_property_returns_default(self) -> None:
        """Test model property returns provider default when not set."""
        service = TTSService()

        assert service.model == "tts-1"

    def test_model_property_returns_explicit(self) -> None:
        """Test model property returns explicit model when set."""
        service = TTSService(model="tts-1-hd")

        assert service.model == "tts-1-hd"

    def test_voice_property_returns_default(self) -> None:
        """Test voice property returns provider default when not set."""
        service = TTSService()

        assert service.voice == "alloy"

    def test_voice_property_returns_explicit(self) -> None:
        """Test voice property returns explicit voice when set."""
        service = TTSService(voice="nova")

        assert service.voice == "nova"


class TestTTSServiceProviderManagement:
    """Test TTSService provider management."""

    def test_provider_lazy_loaded(self) -> None:
        """Test provider is not created until needed."""
        service = TTSService()

        assert service._provider_instance is None

    def test_reset_provider_clears_instance(self) -> None:
        """Test reset_provider clears the cached provider."""
        service = TTSService()
        # Force provider creation
        service._provider_instance = MagicMock()

        service.reset_provider()

        assert service._provider_instance is None


class TestTTSServiceValidation:
    """Test TTSService validation methods."""

    def test_validate_with_valid_config(self) -> None:
        """Test validate returns empty list for valid config."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-key"

        service = TTSService(settings)
        errors = service.validate()

        assert len(errors) == 0

    def test_validate_with_missing_api_key(self) -> None:
        """Test validate returns errors for missing API key."""
        settings = MagicMock(spec=[])

        service = TTSService(settings)
        errors = service.validate()

        assert len(errors) == 1
        assert "OPENAI_API_KEY" in errors[0]

    def test_is_available_true_when_valid(self) -> None:
        """Test is_available returns True when validation passes."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-key"

        service = TTSService(settings)

        assert service.is_available() is True

    def test_is_available_false_when_invalid(self) -> None:
        """Test is_available returns False when validation fails."""
        settings = MagicMock(spec=[])

        service = TTSService(settings)

        assert service.is_available() is False


class TestTTSServiceStatus:
    """Test TTSService.get_status() method."""

    def test_get_status_returns_dict(self) -> None:
        """Test get_status returns status dictionary."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-key"
        settings.TTS_PROVIDER = "openai"
        settings.TTS_MODEL = None
        settings.TTS_VOICE = None
        settings.TTS_SPEED = 1.0

        service = TTSService(settings)
        status = service.get_status()

        assert isinstance(status, dict)
        assert status["provider"] == "openai"
        assert status["model"] == "tts-1"
        assert status["voice"] == "alloy"
        assert status["speed"] == 1.0
        assert status["initialized"] is False
        assert status["available"] is True

    def test_get_status_shows_not_available(self) -> None:
        """Test get_status shows not available when invalid."""
        settings = MagicMock(spec=[])

        service = TTSService(settings)
        status = service.get_status()

        assert status["available"] is False
        assert status["errors"] is not None

    def test_get_status_shows_initialized(self) -> None:
        """Test get_status shows initialized when provider created."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-key"
        settings.TTS_PROVIDER = "openai"
        settings.TTS_MODEL = None
        settings.TTS_VOICE = None
        settings.TTS_SPEED = 1.0

        service = TTSService(settings)
        # Force provider creation
        service._provider_instance = MagicMock()

        status = service.get_status()

        assert status["initialized"] is True
