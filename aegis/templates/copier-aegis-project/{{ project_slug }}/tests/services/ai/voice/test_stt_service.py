"""Tests for STT service."""

from unittest.mock import MagicMock

from app.services.ai.domains.voice.models import STTProvider
from app.services.ai.domains.voice.stt import STTConfig, STTService


class TestSTTServiceInitialization:
    """Test STTService initialization."""

    def test_init_with_settings(self) -> None:
        """Test initialization with settings loads config from settings."""
        settings = MagicMock()
        settings.STT_PROVIDER = "groq_whisper"
        settings.STT_MODEL = "whisper-large-v3"
        settings.STT_LANGUAGE = "en"
        settings.STT_DEVICE = None

        service = STTService(settings)

        assert service.provider_type == STTProvider.GROQ_WHISPER
        assert service.config.language == "en"

    def test_init_with_explicit_provider(self) -> None:
        """Test initialization with explicit provider overrides settings."""
        settings = MagicMock()
        settings.STT_PROVIDER = "openai_whisper"
        settings.STT_MODEL = None
        settings.STT_LANGUAGE = None
        settings.STT_DEVICE = None

        service = STTService(settings, provider=STTProvider.GROQ_WHISPER)

        assert service.provider_type == STTProvider.GROQ_WHISPER

    def test_init_with_explicit_model(self) -> None:
        """Test initialization with explicit model overrides settings."""
        settings = MagicMock()
        settings.STT_PROVIDER = "openai_whisper"
        settings.STT_MODEL = "settings-model"
        settings.STT_LANGUAGE = None
        settings.STT_DEVICE = None

        service = STTService(settings, model="explicit-model")

        assert service.model == "explicit-model"

    def test_init_without_settings_uses_defaults(self) -> None:
        """Test initialization without settings uses default config."""
        service = STTService()

        assert service.provider_type == STTProvider.OPENAI_WHISPER
        assert service.model == "whisper-1"  # Default for OpenAI

    def test_init_provider_instance_is_none(self) -> None:
        """Test provider instance is None until first use (lazy loading)."""
        service = STTService()

        # Access internal state to verify lazy loading
        assert service._provider_instance is None


class TestSTTServiceProperties:
    """Test STTService properties."""

    def test_config_property(self) -> None:
        """Test config property returns STTConfig instance."""
        service = STTService()

        assert isinstance(service.config, STTConfig)

    def test_provider_type_property(self) -> None:
        """Test provider_type property returns correct enum."""
        service = STTService(provider=STTProvider.FASTER_WHISPER)

        assert service.provider_type == STTProvider.FASTER_WHISPER

    def test_model_property_with_explicit_model(self) -> None:
        """Test model property returns explicit model when set."""
        service = STTService(model="custom-model")

        assert service.model == "custom-model"

    def test_model_property_with_default(self) -> None:
        """Test model property returns provider default when not set."""
        service = STTService(provider=STTProvider.GROQ_WHISPER)

        assert service.model == "whisper-large-v3-turbo"


class TestSTTServiceStatus:
    """Test STTService.get_status() method."""

    def test_get_status_structure(self) -> None:
        """Test get_status returns expected structure."""
        service = STTService()
        status = service.get_status()

        assert isinstance(status, dict)
        assert "provider" in status
        assert "model" in status
        assert "language" in status
        assert "device" in status
        assert "initialized" in status
        assert "available" in status
        assert "errors" in status

    def test_get_status_provider_is_string(self) -> None:
        """Test provider in status is string value."""
        service = STTService(provider=STTProvider.OPENAI_WHISPER)
        status = service.get_status()

        assert status["provider"] == "openai_whisper"

    def test_get_status_not_initialized_before_use(self) -> None:
        """Test initialized is False before first transcription."""
        service = STTService()
        status = service.get_status()

        assert status["initialized"] is False

    def test_get_status_errors_none_when_valid(self) -> None:
        """Test errors is None when no validation errors."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-key"
        settings.STT_PROVIDER = "openai_whisper"
        settings.STT_MODEL = None
        settings.STT_LANGUAGE = None
        settings.STT_DEVICE = None

        service = STTService(settings)
        status = service.get_status()

        assert status["errors"] is None
        assert status["available"] is True

    def test_get_status_errors_present_when_invalid(self) -> None:
        """Test errors contains messages when validation fails."""
        settings = MagicMock(
            spec=["STT_PROVIDER", "STT_MODEL", "STT_LANGUAGE", "STT_DEVICE"]
        )
        settings.STT_PROVIDER = "openai_whisper"
        settings.STT_MODEL = None
        settings.STT_LANGUAGE = None
        settings.STT_DEVICE = None

        service = STTService(settings)
        status = service.get_status()

        assert status["errors"] is not None
        assert len(status["errors"]) > 0
        assert status["available"] is False


class TestSTTServiceValidation:
    """Test STTService validation methods."""

    def test_validate_returns_list(self) -> None:
        """Test validate returns list of error strings."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-key"
        settings.STT_PROVIDER = "openai_whisper"
        settings.STT_MODEL = None
        settings.STT_LANGUAGE = None
        settings.STT_DEVICE = None

        service = STTService(settings)
        errors = service.validate()

        assert isinstance(errors, list)
        assert all(isinstance(e, str) for e in errors)

    def test_validate_without_settings_returns_empty(self) -> None:
        """Test validate returns empty list when no settings."""
        service = STTService()
        errors = service.validate()

        assert errors == []

    def test_is_available_true_when_valid(self) -> None:
        """Test is_available returns True when valid."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-key"
        settings.STT_PROVIDER = "openai_whisper"
        settings.STT_MODEL = None
        settings.STT_LANGUAGE = None
        settings.STT_DEVICE = None

        service = STTService(settings)

        assert service.is_available() is True

    def test_is_available_false_when_invalid(self) -> None:
        """Test is_available returns False when invalid."""
        settings = MagicMock(
            spec=["STT_PROVIDER", "STT_MODEL", "STT_LANGUAGE", "STT_DEVICE"]
        )
        settings.STT_PROVIDER = "openai_whisper"
        settings.STT_MODEL = None
        settings.STT_LANGUAGE = None
        settings.STT_DEVICE = None

        service = STTService(settings)

        assert service.is_available() is False

    def test_is_available_true_without_settings(self) -> None:
        """Test is_available returns True when no settings (runtime check)."""
        service = STTService()

        # Without settings, assumes available (will fail at runtime)
        assert service.is_available() is True


class TestSTTServiceProviderManagement:
    """Test STTService provider management."""

    def test_reset_provider_clears_instance(self) -> None:
        """Test reset_provider clears the cached provider instance."""
        service = STTService()

        # Manually set a mock provider
        service._provider_instance = MagicMock()
        assert service._provider_instance is not None

        service.reset_provider()

        assert service._provider_instance is None


class TestSTTServiceApiKey:
    """Test STTService API key handling."""

    def test_explicit_api_key_used(self) -> None:
        """Test explicit API key is used over settings."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "settings-key"
        settings.STT_PROVIDER = "openai_whisper"
        settings.STT_MODEL = None
        settings.STT_LANGUAGE = None
        settings.STT_DEVICE = None

        service = STTService(settings, api_key="explicit-key")

        # Access internal method to verify
        assert service._get_api_key() == "explicit-key"

    def test_settings_api_key_used_when_no_explicit(self) -> None:
        """Test settings API key is used when no explicit key."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "settings-key"
        settings.STT_PROVIDER = "openai_whisper"
        settings.STT_MODEL = None
        settings.STT_LANGUAGE = None
        settings.STT_DEVICE = None

        service = STTService(settings)

        assert service._get_api_key() == "settings-key"

    def test_no_api_key_without_settings(self) -> None:
        """Test no API key returned without settings."""
        service = STTService()

        assert service._get_api_key() is None
