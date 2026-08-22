"""Tests for voice catalog functions."""

from app.services.ai.domains.voice import (
    OpenAIVoice,
    STTProvider,
    TTSProvider,
    get_current_voice_config,
    get_stt_models,
    get_stt_providers,
    get_tts_models,
    get_tts_providers,
    get_tts_voices,
    get_voice,
)
from app.services.ai.domains.voice.models import ModelInfo, ProviderInfo, VoiceInfo


class TestGetTtsProviders:
    """Tests for get_tts_providers() function."""

    def test_get_tts_providers_returns_list(self) -> None:
        """Test that get_tts_providers returns a list."""
        providers = get_tts_providers()
        assert isinstance(providers, list)

    def test_get_tts_providers_not_empty(self) -> None:
        """Test that get_tts_providers returns non-empty list."""
        providers = get_tts_providers()
        assert len(providers) > 0

    def test_get_tts_providers_contains_openai(self) -> None:
        """Test that OpenAI is included in TTS providers."""
        providers = get_tts_providers()
        provider_ids = [p.id for p in providers]
        assert TTSProvider.OPENAI.value in provider_ids

    def test_get_tts_providers_returns_provider_info_objects(self) -> None:
        """Test that returned items are ProviderInfo objects."""
        providers = get_tts_providers()
        for provider in providers:
            assert isinstance(provider, ProviderInfo)
            assert provider.id is not None
            assert provider.name is not None
            assert provider.type == "tts"

    def test_get_tts_providers_returns_copy(self) -> None:
        """Test that returned list is a copy, not the original."""
        providers1 = get_tts_providers()
        providers2 = get_tts_providers()
        # Should be equal but different list objects
        assert providers1 is not providers2
        assert len(providers1) == len(providers2)


class TestGetTtsModels:
    """Tests for get_tts_models() function."""

    def test_get_tts_models_returns_list(self) -> None:
        """Test that get_tts_models returns a list."""
        models = get_tts_models()
        assert isinstance(models, list)

    def test_get_tts_models_not_empty(self) -> None:
        """Test that get_tts_models returns non-empty list."""
        models = get_tts_models()
        assert len(models) > 0

    def test_get_tts_models_without_filter(self) -> None:
        """Test getting all TTS models without provider filter."""
        models = get_tts_models()
        assert isinstance(models, list)
        assert len(models) > 0
        for model in models:
            assert isinstance(model, ModelInfo)
            assert model.id is not None
            assert model.provider_id is not None

    def test_get_tts_models_filtered_by_provider(self) -> None:
        """Test getting TTS models filtered by provider."""
        models = get_tts_models(provider_id=TTSProvider.OPENAI.value)
        assert len(models) > 0
        for model in models:
            assert model.provider_id == TTSProvider.OPENAI.value

    def test_get_tts_models_invalid_provider_returns_empty(self) -> None:
        """Test that invalid provider returns empty list."""
        models = get_tts_models(provider_id="invalid_provider")
        assert models == []

    def test_get_tts_models_returns_copy(self) -> None:
        """Test that returned list is a copy."""
        models1 = get_tts_models()
        models2 = get_tts_models()
        assert models1 is not models2
        assert len(models1) == len(models2)


class TestGetTtsVoices:
    """Tests for get_tts_voices() function."""

    def test_get_tts_voices_returns_list(self) -> None:
        """Test that get_tts_voices returns a list."""
        voices = get_tts_voices()
        assert isinstance(voices, list)

    def test_get_tts_voices_not_empty(self) -> None:
        """Test that get_tts_voices returns non-empty list."""
        voices = get_tts_voices()
        assert len(voices) > 0

    def test_get_tts_voices_without_filter(self) -> None:
        """Test getting all TTS voices."""
        voices = get_tts_voices()
        assert len(voices) > 0
        for voice in voices:
            assert isinstance(voice, VoiceInfo)
            assert voice.id is not None
            assert voice.provider_id is not None

    def test_get_tts_voices_filtered_by_provider(self) -> None:
        """Test getting voices filtered by provider."""
        voices = get_tts_voices(provider_id=TTSProvider.OPENAI.value)
        assert len(voices) > 0
        for voice in voices:
            assert voice.provider_id == TTSProvider.OPENAI.value

    def test_get_tts_voices_filtered_by_model(self) -> None:
        """Test getting voices filtered by model."""
        voices = get_tts_voices(model_id="tts-1")
        assert len(voices) > 0
        for voice in voices:
            assert "tts-1" in voice.model_ids

    def test_get_tts_voices_filtered_by_provider_and_model(self) -> None:
        """Test getting voices filtered by both provider and model."""
        voices = get_tts_voices(provider_id=TTSProvider.OPENAI.value, model_id="tts-1")
        assert len(voices) > 0
        for voice in voices:
            assert voice.provider_id == TTSProvider.OPENAI.value
            assert "tts-1" in voice.model_ids

    def test_get_tts_voices_invalid_provider_returns_empty(self) -> None:
        """Test that invalid provider returns empty list."""
        voices = get_tts_voices(provider_id="invalid_provider")
        assert voices == []

    def test_get_tts_voices_invalid_model_returns_empty(self) -> None:
        """Test that invalid model returns empty list."""
        voices = get_tts_voices(model_id="invalid_model")
        assert voices == []

    def test_get_tts_voices_contains_alloy(self) -> None:
        """Test that Alloy voice is included."""
        voices = get_tts_voices(provider_id=TTSProvider.OPENAI.value)
        voice_ids = [v.id for v in voices]
        assert OpenAIVoice.ALLOY.value in voice_ids

    def test_get_tts_voices_returns_copy(self) -> None:
        """Test that returned list is a copy."""
        voices1 = get_tts_voices()
        voices2 = get_tts_voices()
        assert voices1 is not voices2
        assert len(voices1) == len(voices2)


class TestGetVoice:
    """Tests for get_voice() function."""

    def test_get_voice_by_id(self) -> None:
        """Test getting a specific voice by ID."""
        voice = get_voice(OpenAIVoice.ALLOY.value)
        assert voice is not None
        assert voice.id == OpenAIVoice.ALLOY.value
        assert voice.name == "Alloy"

    def test_get_voice_returns_voice_info(self) -> None:
        """Test that returned object is VoiceInfo."""
        voice = get_voice(OpenAIVoice.ECHO.value)
        assert isinstance(voice, VoiceInfo)
        assert voice.id == OpenAIVoice.ECHO.value

    def test_get_voice_invalid_id_returns_none(self) -> None:
        """Test that invalid voice ID returns None."""
        voice = get_voice("invalid_voice_id")
        assert voice is None

    def test_get_voice_different_voices(self) -> None:
        """Test retrieving different voices."""
        voice_ids = [
            OpenAIVoice.ALLOY.value,
            OpenAIVoice.ECHO.value,
            OpenAIVoice.FABLE.value,
            OpenAIVoice.ONYX.value,
            OpenAIVoice.NOVA.value,
            OpenAIVoice.SHIMMER.value,
        ]
        for voice_id in voice_ids:
            voice = get_voice(voice_id)
            assert voice is not None
            assert voice.id == voice_id


class TestGetSttProviders:
    """Tests for get_stt_providers() function."""

    def test_get_stt_providers_returns_list(self) -> None:
        """Test that get_stt_providers returns a list."""
        providers = get_stt_providers()
        assert isinstance(providers, list)

    def test_get_stt_providers_not_empty(self) -> None:
        """Test that get_stt_providers returns non-empty list."""
        providers = get_stt_providers()
        assert len(providers) > 0

    def test_get_stt_providers_contains_openai(self) -> None:
        """Test that OpenAI Whisper is included."""
        providers = get_stt_providers()
        provider_ids = [p.id for p in providers]
        assert STTProvider.OPENAI_WHISPER.value in provider_ids

    def test_get_stt_providers_contains_groq(self) -> None:
        """Test that Groq Whisper is included."""
        providers = get_stt_providers()
        provider_ids = [p.id for p in providers]
        assert STTProvider.GROQ_WHISPER.value in provider_ids

    def test_get_stt_providers_contains_faster_whisper(self) -> None:
        """Test that Faster Whisper is included."""
        providers = get_stt_providers()
        provider_ids = [p.id for p in providers]
        assert STTProvider.FASTER_WHISPER.value in provider_ids

    def test_get_stt_providers_returns_provider_info_objects(self) -> None:
        """Test that returned items are ProviderInfo objects."""
        providers = get_stt_providers()
        for provider in providers:
            assert isinstance(provider, ProviderInfo)
            assert provider.id is not None
            assert provider.name is not None
            assert provider.type == "stt"

    def test_get_stt_providers_returns_copy(self) -> None:
        """Test that returned list is a copy."""
        providers1 = get_stt_providers()
        providers2 = get_stt_providers()
        assert providers1 is not providers2
        assert len(providers1) == len(providers2)


class TestGetSttModels:
    """Tests for get_stt_models() function."""

    def test_get_stt_models_returns_list(self) -> None:
        """Test that get_stt_models returns a list."""
        models = get_stt_models()
        assert isinstance(models, list)

    def test_get_stt_models_not_empty(self) -> None:
        """Test that get_stt_models returns non-empty list."""
        models = get_stt_models()
        assert len(models) > 0

    def test_get_stt_models_without_filter(self) -> None:
        """Test getting all STT models."""
        models = get_stt_models()
        assert len(models) > 0
        for model in models:
            assert isinstance(model, ModelInfo)
            assert model.id is not None
            assert model.provider_id is not None

    def test_get_stt_models_filtered_by_openai(self) -> None:
        """Test getting STT models filtered by OpenAI Whisper."""
        models = get_stt_models(provider_id=STTProvider.OPENAI_WHISPER.value)
        assert len(models) > 0
        for model in models:
            assert model.provider_id == STTProvider.OPENAI_WHISPER.value

    def test_get_stt_models_filtered_by_groq(self) -> None:
        """Test getting STT models filtered by Groq."""
        models = get_stt_models(provider_id=STTProvider.GROQ_WHISPER.value)
        assert len(models) > 0
        for model in models:
            assert model.provider_id == STTProvider.GROQ_WHISPER.value

    def test_get_stt_models_filtered_by_faster_whisper(self) -> None:
        """Test getting STT models filtered by Faster Whisper."""
        models = get_stt_models(provider_id=STTProvider.FASTER_WHISPER.value)
        assert len(models) > 0
        for model in models:
            assert model.provider_id == STTProvider.FASTER_WHISPER.value

    def test_get_stt_models_invalid_provider_returns_empty(self) -> None:
        """Test that invalid provider returns empty list."""
        models = get_stt_models(provider_id="invalid_provider")
        assert models == []

    def test_get_stt_models_returns_copy(self) -> None:
        """Test that returned list is a copy."""
        models1 = get_stt_models()
        models2 = get_stt_models()
        assert models1 is not models2
        assert len(models1) == len(models2)


class TestGetCurrentVoiceConfig:
    """Tests for get_current_voice_config() function."""

    def test_get_current_voice_config_returns_dict(
        self, mock_voice_settings: object
    ) -> None:
        """Test that function returns a dictionary."""
        config = get_current_voice_config(mock_voice_settings)
        assert isinstance(config, dict)

    def test_get_current_voice_config_has_required_keys(
        self, mock_voice_settings: object
    ) -> None:
        """Test that config has all required keys."""
        config = get_current_voice_config(mock_voice_settings)
        required_keys = [
            "tts_provider",
            "tts_model",
            "tts_voice",
            "tts_speed",
            "stt_provider",
            "stt_model",
            "stt_language",
        ]
        for key in required_keys:
            assert key in config

    def test_get_current_voice_config_uses_settings_values(
        self, mock_voice_settings: object
    ) -> None:
        """Test that config uses values from settings."""
        config = get_current_voice_config(mock_voice_settings)
        assert config["tts_provider"] == TTSProvider.OPENAI.value
        assert config["tts_model"] == "tts-1"
        assert config["tts_voice"] == OpenAIVoice.ALLOY.value
        assert config["tts_speed"] == 1.0
        assert config["stt_provider"] == STTProvider.OPENAI_WHISPER.value
        assert config["stt_model"] == "whisper-1"
        assert config["stt_language"] is None

    def test_get_current_voice_config_with_defaults(self) -> None:
        """Test that missing settings use defaults."""
        settings = object()
        config = get_current_voice_config(settings)
        # Should use defaults when attributes don't exist
        assert config["tts_provider"] == TTSProvider.OPENAI.value
        assert config["tts_model"] == "tts-1"
        assert config["tts_voice"] == OpenAIVoice.ALLOY.value
        assert config["tts_speed"] == 1.0
        assert config["stt_provider"] == STTProvider.OPENAI_WHISPER.value
        assert config["stt_model"] == "whisper-1"

    def test_get_current_voice_config_with_none_values(self) -> None:
        """Test that None values fall back to defaults."""
        from unittest.mock import MagicMock

        settings = MagicMock()
        settings.TTS_PROVIDER = None
        settings.TTS_MODEL = None
        settings.TTS_VOICE = None
        settings.TTS_SPEED = None
        settings.STT_PROVIDER = None
        settings.STT_MODEL = None
        settings.STT_LANGUAGE = None

        config = get_current_voice_config(settings)
        # Should use defaults for None values
        assert config["tts_provider"] == TTSProvider.OPENAI.value
        assert config["tts_model"] == "tts-1"
        assert config["tts_voice"] == OpenAIVoice.ALLOY.value
        assert config["tts_speed"] == 1.0
        assert config["stt_provider"] == STTProvider.OPENAI_WHISPER.value
        assert config["stt_model"] == "whisper-1"

    def test_get_current_voice_config_with_custom_values(self) -> None:
        """Test config with custom settings values."""
        from unittest.mock import MagicMock

        settings = MagicMock()
        settings.TTS_PROVIDER = TTSProvider.OPENAI.value
        settings.TTS_MODEL = "tts-1-hd"
        settings.TTS_VOICE = OpenAIVoice.ECHO.value
        settings.TTS_SPEED = 0.8
        settings.STT_PROVIDER = STTProvider.GROQ_WHISPER.value
        settings.STT_MODEL = "whisper-large-v3"
        settings.STT_LANGUAGE = "en"

        config = get_current_voice_config(settings)
        assert config["tts_provider"] == TTSProvider.OPENAI.value
        assert config["tts_model"] == "tts-1-hd"
        assert config["tts_voice"] == OpenAIVoice.ECHO.value
        assert config["tts_speed"] == 0.8
        assert config["stt_provider"] == STTProvider.GROQ_WHISPER.value
        assert config["stt_model"] == "whisper-large-v3"
        assert config["stt_language"] == "en"
