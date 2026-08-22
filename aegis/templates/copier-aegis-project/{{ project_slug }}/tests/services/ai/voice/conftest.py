"""Shared fixtures for voice service tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.ai.domains.voice import (
    AudioFormat,
    ModelInfo,
    OpenAIVoice,
    ProviderInfo,
    SpeechResult,
    STTProvider,
    TTSProvider,
    VoiceCategory,
    VoiceInfo,
    VoiceSettingsResponse,
)


@pytest.fixture
def mock_voice_settings() -> MagicMock:
    """Create mock settings for voice service testing."""
    settings = MagicMock()
    settings.TTS_PROVIDER = TTSProvider.OPENAI.value
    settings.TTS_MODEL = "tts-1"
    settings.TTS_VOICE = OpenAIVoice.ALLOY.value
    settings.TTS_SPEED = 1.0
    settings.STT_PROVIDER = STTProvider.OPENAI_WHISPER.value
    settings.STT_MODEL = "whisper-1"
    settings.STT_LANGUAGE = None
    return settings


@pytest.fixture
def sample_tts_provider() -> ProviderInfo:
    """Create a sample TTS provider."""
    return ProviderInfo(
        id=TTSProvider.OPENAI.value,
        name="OpenAI",
        type="tts",
        requires_api_key=True,
        api_key_env_var="OPENAI_API_KEY",
        is_local=False,
        description="OpenAI Text-to-Speech API",
    )


@pytest.fixture
def sample_stt_provider() -> ProviderInfo:
    """Create a sample STT provider."""
    return ProviderInfo(
        id=STTProvider.OPENAI_WHISPER.value,
        name="OpenAI Whisper",
        type="stt",
        requires_api_key=True,
        api_key_env_var="OPENAI_API_KEY",
        is_local=False,
        description="OpenAI Whisper API",
    )


@pytest.fixture
def sample_tts_model() -> ModelInfo:
    """Create a sample TTS model."""
    return ModelInfo(
        id="tts-1",
        name="TTS-1",
        provider_id=TTSProvider.OPENAI.value,
        quality="standard",
        description="Standard quality TTS model",
        supports_streaming=True,
    )


@pytest.fixture
def sample_stt_model() -> ModelInfo:
    """Create a sample STT model."""
    return ModelInfo(
        id="whisper-1",
        name="Whisper-1",
        provider_id=STTProvider.OPENAI_WHISPER.value,
        quality="standard",
        description="OpenAI Whisper transcription model",
        supports_streaming=False,
    )


@pytest.fixture
def sample_voice() -> VoiceInfo:
    """Create a sample voice."""
    return VoiceInfo(
        id=OpenAIVoice.ALLOY.value,
        name="Alloy",
        provider_id=TTSProvider.OPENAI.value,
        model_ids=["tts-1", "tts-1-hd"],
        description="Neutral, balanced voice",
        category=VoiceCategory.NEUTRAL,
        gender="neutral",
        preview_text="Hello, I'm {voice_name}. How can I help?",
    )


@pytest.fixture
def sample_voice_settings() -> VoiceSettingsResponse:
    """Create sample voice settings."""
    return VoiceSettingsResponse(
        tts_provider=TTSProvider.OPENAI.value,
        tts_model="tts-1",
        tts_voice=OpenAIVoice.ALLOY.value,
        tts_speed=1.0,
        stt_provider=STTProvider.OPENAI_WHISPER.value,
        stt_model="whisper-1",
        stt_language=None,
    )


@pytest.fixture
def mock_speech_result() -> SpeechResult:
    """Create a mock speech result."""
    return SpeechResult(
        audio=b"mock_audio_data",
        format=AudioFormat.MP3,
        duration_seconds=2.5,
        provider=TTSProvider.OPENAI,
    )


@pytest.fixture
def mock_tts_service() -> AsyncMock:
    """Create a mock TTS service."""
    service = AsyncMock()
    service.synthesize = AsyncMock(
        return_value=SpeechResult(
            audio=b"mock_audio_data",
            format=AudioFormat.MP3,
            duration_seconds=2.5,
            provider=TTSProvider.OPENAI,
        )
    )
    return service


@pytest.fixture
def mock_ai_service(mock_tts_service: AsyncMock) -> MagicMock:
    """Create a mock AI service with TTS component."""
    service = MagicMock()
    service.tts = mock_tts_service
    return service
