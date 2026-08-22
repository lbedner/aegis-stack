"""Tests for TTS models."""

import pytest
from app.services.ai.domains.voice.models import (
    AudioFormat,
    OpenAIVoice,
    SpeechRequest,
    SpeechResult,
    TTSProvider,
)


class TestTTSProvider:
    """Test TTSProvider enum."""

    def test_openai_provider(self) -> None:
        """Test OpenAI provider value."""
        assert TTSProvider.OPENAI.value == "openai"

    def test_all_providers_are_strings(self) -> None:
        """Test all providers have string values."""
        for provider in TTSProvider:
            assert isinstance(provider.value, str)


class TestOpenAIVoice:
    """Test OpenAIVoice enum."""

    def test_all_voices_exist(self) -> None:
        """Test all expected OpenAI voices exist."""
        expected_voices = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

        for voice_name in expected_voices:
            assert OpenAIVoice(voice_name) is not None

    def test_voice_values(self) -> None:
        """Test voice values are lowercase strings."""
        for voice in OpenAIVoice:
            assert isinstance(voice.value, str)
            assert voice.value == voice.value.lower()


class TestSpeechRequest:
    """Test SpeechRequest model."""

    def test_required_text(self) -> None:
        """Test text is required."""
        request = SpeechRequest(text="Hello, world!")

        assert request.text == "Hello, world!"

    def test_optional_voice(self) -> None:
        """Test voice is optional."""
        request = SpeechRequest(text="Hello")

        assert request.voice is None

    def test_explicit_voice(self) -> None:
        """Test voice can be set explicitly."""
        request = SpeechRequest(text="Hello", voice="nova")

        assert request.voice == "nova"

    def test_optional_language(self) -> None:
        """Test language is optional."""
        request = SpeechRequest(text="Hello")

        assert request.language is None

    def test_explicit_language(self) -> None:
        """Test language can be set explicitly."""
        request = SpeechRequest(text="Hello", language="en")

        assert request.language == "en"

    def test_default_speed(self) -> None:
        """Test speed defaults to 1.0."""
        request = SpeechRequest(text="Hello")

        assert request.speed == 1.0

    def test_custom_speed(self) -> None:
        """Test speed can be set."""
        request = SpeechRequest(text="Hello", speed=1.5)

        assert request.speed == 1.5

    def test_speed_validation_min(self) -> None:
        """Test speed cannot be less than 0.25."""
        with pytest.raises(ValueError):
            SpeechRequest(text="Hello", speed=0.1)

    def test_speed_validation_max(self) -> None:
        """Test speed cannot be greater than 4.0."""
        with pytest.raises(ValueError):
            SpeechRequest(text="Hello", speed=5.0)

    def test_speed_boundary_min(self) -> None:
        """Test speed can be exactly 0.25."""
        request = SpeechRequest(text="Hello", speed=0.25)

        assert request.speed == 0.25

    def test_speed_boundary_max(self) -> None:
        """Test speed can be exactly 4.0."""
        request = SpeechRequest(text="Hello", speed=4.0)

        assert request.speed == 4.0


class TestSpeechResult:
    """Test SpeechResult model."""

    def test_required_fields(self) -> None:
        """Test required fields are set."""
        result = SpeechResult(
            audio=b"fake-audio-data",
            format=AudioFormat.MP3,
            provider=TTSProvider.OPENAI,
        )

        assert result.audio == b"fake-audio-data"
        assert result.format == AudioFormat.MP3
        assert result.provider == TTSProvider.OPENAI

    def test_optional_duration(self) -> None:
        """Test duration_seconds is optional."""
        result = SpeechResult(
            audio=b"fake-audio-data",
            format=AudioFormat.MP3,
            provider=TTSProvider.OPENAI,
        )

        assert result.duration_seconds is None

    def test_explicit_duration(self) -> None:
        """Test duration_seconds can be set."""
        result = SpeechResult(
            audio=b"fake-audio-data",
            format=AudioFormat.MP3,
            provider=TTSProvider.OPENAI,
            duration_seconds=2.5,
        )

        assert result.duration_seconds == 2.5

    def test_audio_bytes(self) -> None:
        """Test audio is bytes."""
        result = SpeechResult(
            audio=b"\x00\x01\x02",
            format=AudioFormat.MP3,
            provider=TTSProvider.OPENAI,
        )

        assert isinstance(result.audio, bytes)
        assert len(result.audio) == 3
