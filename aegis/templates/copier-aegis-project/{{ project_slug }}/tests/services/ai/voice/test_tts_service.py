"""Tests for TTS service."""

from unittest.mock import AsyncMock, MagicMock

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
        settings.TTS_INSTRUCTIONS = None

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

    async def test_validate_with_valid_config(self) -> None:
        """Test validate returns empty list for valid config."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-key"
        settings.TTS_PROVIDER = "openai"
        settings.TTS_MODEL = None
        settings.TTS_VOICE = None
        settings.TTS_SPEED = 1.0
        settings.TTS_INSTRUCTIONS = None

        service = TTSService(settings)
        errors = await service.validate()

        assert len(errors) == 0

    async def test_validate_with_missing_api_key(self) -> None:
        """Test validate returns errors for missing API key."""
        settings = MagicMock(spec=[])

        service = TTSService(settings)
        errors = await service.validate()

        assert len(errors) == 1
        assert "OPENAI_API_KEY" in errors[0]

    async def test_is_available_true_when_valid(self) -> None:
        """Test is_available returns True when validation passes."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-key"
        settings.TTS_PROVIDER = "openai"
        settings.TTS_MODEL = None
        settings.TTS_VOICE = None
        settings.TTS_SPEED = 1.0
        settings.TTS_INSTRUCTIONS = None

        service = TTSService(settings)

        assert await service.is_available() is True

    async def test_is_available_false_when_invalid(self) -> None:
        """Test is_available returns False when validation fails."""
        settings = MagicMock(spec=[])

        service = TTSService(settings)

        assert await service.is_available() is False


class TestTTSServiceStatus:
    """Test TTSService.get_status() method."""

    async def test_get_status_returns_dict(self) -> None:
        """Test get_status returns status dictionary."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-key"
        settings.TTS_PROVIDER = "openai"
        settings.TTS_MODEL = None
        settings.TTS_VOICE = None
        settings.TTS_SPEED = 1.0
        settings.TTS_INSTRUCTIONS = None

        service = TTSService(settings)
        status = await service.get_status()

        assert isinstance(status, dict)
        assert status["provider"] == "openai"
        assert status["model"] == "tts-1"
        assert status["voice"] == "alloy"
        assert status["speed"] == 1.0
        assert status["initialized"] is False
        assert status["available"] is True

    async def test_get_status_shows_not_available(self) -> None:
        """Test get_status shows not available when invalid."""
        settings = MagicMock(spec=[])

        service = TTSService(settings)
        status = await service.get_status()

        assert status["available"] is False
        assert status["errors"] is not None

    async def test_get_status_shows_initialized(self) -> None:
        """Test get_status shows initialized when provider created."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "sk-test-key"
        settings.TTS_PROVIDER = "openai"
        settings.TTS_MODEL = None
        settings.TTS_VOICE = None
        settings.TTS_SPEED = 1.0
        settings.TTS_INSTRUCTIONS = None

        service = TTSService(settings)
        # Force provider creation
        service._provider_instance = MagicMock()

        status = await service.get_status()

        assert status["initialized"] is True


class TestStreamingRecordsUsage:
    """A streamed synthesis is recorded like a whole one, against the
    speaker, once the last chunk has gone."""

    async def test_usage_is_recorded_after_the_stream(self, monkeypatch) -> None:  # noqa: ANN001
        from unittest.mock import AsyncMock, MagicMock

        from app.services.ai.domains.voice.models import SpeechRequest
        from app.services.ai.domains.voice.tts.service import TTSService

        async def _chunks(request):  # noqa: ANN001, ANN202
            yield b"ab"
            yield b"cde"

        provider = MagicMock()
        provider.synthesize_stream = _chunks
        service = TTSService(
            MagicMock(
                TTS_PROVIDER="openai",
                TTS_MODEL=None,
                TTS_VOICE=None,
                TTS_SPEED=1.0,
                TTS_INSTRUCTIONS=None,
                OPENAI_API_KEY="k",
            )
        )
        monkeypatch.setattr(service, "_get_provider", AsyncMock(return_value=provider))
        record = AsyncMock()
        monkeypatch.setattr(service, "_record_usage", record)

        got = [
            c
            async for c in service.synthesize_stream(
                SpeechRequest(text="Hello"), user_id="0"
            )
        ]

        assert got == [b"ab", b"cde"]
        kwargs = record.call_args.kwargs
        assert kwargs["user_id"] == "0"
        assert kwargs["input_characters"] == 5
        assert kwargs["success"] is True


class TestTheConfiguredVoiceIsUsed:
    """TTS_SPEED was read into the config and never reached the provider:
    every request carried SpeechRequest's own default of 1.0.
    What a request leaves unset comes from the settings; what it sets wins."""

    def _service(self, monkeypatch, speed: float, instructions: str | None):  # noqa: ANN001, ANN202
        from unittest.mock import MagicMock

        from app.services.ai.domains.voice.tts.service import TTSService

        seen: list = []

        async def _chunks(request):  # noqa: ANN001, ANN202
            seen.append(request)
            yield b"x"

        provider = MagicMock()
        provider.synthesize_stream = _chunks
        settings = MagicMock(
            TTS_PROVIDER="openai",
            TTS_MODEL=None,
            TTS_VOICE=None,
            TTS_SPEED=speed,
            TTS_INSTRUCTIONS=instructions,
            OPENAI_API_KEY="k",
        )
        service = TTSService(settings)
        monkeypatch.setattr(service, "_get_provider", AsyncMock(return_value=provider))
        monkeypatch.setattr(service, "_record_usage", AsyncMock())
        return service, seen

    async def test_speed_and_instructions_come_from_the_settings(
        self, monkeypatch
    ) -> None:  # noqa: ANN001
        from app.services.ai.domains.voice.models import SpeechRequest

        service, seen = self._service(monkeypatch, 1.4, "Warm and brisk.")
        [c async for c in service.synthesize_stream(SpeechRequest(text="Hi"))]
        assert seen[0].speed == 1.4
        assert seen[0].instructions == "Warm and brisk."

    async def test_a_request_that_sets_them_wins(self, monkeypatch) -> None:  # noqa: ANN001
        from app.services.ai.domains.voice.models import SpeechRequest

        service, seen = self._service(monkeypatch, 1.4, "Warm and brisk.")
        request = SpeechRequest(text="Hi", speed=0.9, instructions="Whisper.")
        [c async for c in service.synthesize_stream(request)]
        assert (seen[0].speed, seen[0].instructions) == (0.9, "Whisper.")
