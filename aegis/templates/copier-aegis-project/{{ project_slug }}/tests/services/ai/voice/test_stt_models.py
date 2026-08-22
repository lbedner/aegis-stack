"""Tests for STT models."""

import pytest
from app.services.ai.domains.voice.models import (
    AudioFormat,
    AudioInput,
    STTProvider,
    TranscriptionResult,
    TranscriptionSegment,
    VoiceChatResponse,
)


class TestSTTProviderEnum:
    """Test STTProvider enum."""

    def test_all_providers_defined(self) -> None:
        """Test all expected providers are defined."""
        expected = ["openai_whisper", "whisper_local", "faster_whisper", "groq_whisper"]

        for provider_value in expected:
            provider = STTProvider(provider_value)
            assert provider.value == provider_value

    def test_provider_values(self) -> None:
        """Test provider enum values are strings."""
        assert STTProvider.OPENAI_WHISPER.value == "openai_whisper"
        assert STTProvider.WHISPER_LOCAL.value == "whisper_local"
        assert STTProvider.FASTER_WHISPER.value == "faster_whisper"
        assert STTProvider.GROQ_WHISPER.value == "groq_whisper"

    def test_invalid_provider_raises(self) -> None:
        """Test invalid provider value raises ValueError."""
        with pytest.raises(ValueError):
            STTProvider("invalid_provider")


class TestAudioFormatEnum:
    """Test AudioFormat enum."""

    def test_common_formats_defined(self) -> None:
        """Test common audio formats are defined."""
        assert AudioFormat.WAV.value == "wav"
        assert AudioFormat.MP3.value == "mp3"
        assert AudioFormat.M4A.value == "m4a"
        assert AudioFormat.WEBM.value == "webm"

    def test_format_values_are_lowercase(self) -> None:
        """Test all format values are lowercase file extensions."""
        for fmt in AudioFormat:
            assert fmt.value == fmt.value.lower()
            assert fmt.value.isalnum()


class TestAudioInput:
    """Test AudioInput model."""

    def test_create_with_required_fields(self) -> None:
        """Test creating AudioInput with only required fields."""
        audio = AudioInput(content=b"audio data")

        assert audio.content == b"audio data"
        assert audio.format == AudioFormat.WAV  # Default
        assert audio.sample_rate is None
        assert audio.language is None

    def test_create_with_all_fields(self) -> None:
        """Test creating AudioInput with all fields."""
        audio = AudioInput(
            content=b"audio data",
            format=AudioFormat.MP3,
            sample_rate=44100,
            language="en",
        )

        assert audio.content == b"audio data"
        assert audio.format == AudioFormat.MP3
        assert audio.sample_rate == 44100
        assert audio.language == "en"

    def test_content_is_bytes(self) -> None:
        """Test content field accepts bytes."""
        audio = AudioInput(content=b"\x00\x01\x02\x03")

        assert isinstance(audio.content, bytes)
        assert len(audio.content) == 4

    def test_format_can_be_set_by_value(self) -> None:
        """Test format can be set using enum value string."""
        audio = AudioInput(content=b"data", format="mp3")

        assert audio.format == AudioFormat.MP3


class TestTranscriptionSegment:
    """Test TranscriptionSegment model."""

    def test_create_segment(self) -> None:
        """Test creating a transcription segment."""
        segment = TranscriptionSegment(
            text="Hello world",
            start=0.0,
            end=1.5,
        )

        assert segment.text == "Hello world"
        assert segment.start == 0.0
        assert segment.end == 1.5

    def test_segment_with_confidence(self) -> None:
        """Test segment with optional confidence score."""
        segment = TranscriptionSegment(
            text="Hello",
            start=0.0,
            end=0.5,
            confidence=0.95,
        )

        assert segment.confidence == 0.95

    def test_segment_confidence_default_none(self) -> None:
        """Test segment confidence defaults to None."""
        segment = TranscriptionSegment(text="Hi", start=0.0, end=0.2)

        assert segment.confidence is None


class TestTranscriptionResult:
    """Test TranscriptionResult model."""

    def test_create_result_minimal(self) -> None:
        """Test creating result with minimal fields."""
        result = TranscriptionResult(
            text="Hello world",
            provider=STTProvider.OPENAI_WHISPER,
        )

        assert result.text == "Hello world"
        assert result.provider == STTProvider.OPENAI_WHISPER
        assert result.language is None
        assert result.duration_seconds is None
        assert result.segments is None

    def test_create_result_full(self) -> None:
        """Test creating result with all fields."""
        segments = [
            TranscriptionSegment(text="Hello", start=0.0, end=0.5),
            TranscriptionSegment(text="world", start=0.5, end=1.0),
        ]

        result = TranscriptionResult(
            text="Hello world",
            provider=STTProvider.GROQ_WHISPER,
            language="en",
            duration_seconds=1.0,
            segments=segments,
        )

        assert result.text == "Hello world"
        assert result.language == "en"
        assert result.duration_seconds == 1.0
        assert result.segments is not None
        assert len(result.segments) == 2

    def test_result_provider_is_enum(self) -> None:
        """Test provider field is STTProvider enum."""
        result = TranscriptionResult(
            text="test",
            provider=STTProvider.FASTER_WHISPER,
        )

        assert isinstance(result.provider, STTProvider)


class TestVoiceChatResponse:
    """Test VoiceChatResponse model."""

    def test_create_voice_chat_response(self) -> None:
        """Test creating VoiceChatResponse."""
        transcription = TranscriptionResult(
            text="What is the weather?",
            provider=STTProvider.OPENAI_WHISPER,
        )

        response = VoiceChatResponse(
            transcription=transcription,
            full_response="The weather today is sunny with a high of 75°F.",
            voice_response="It's sunny, 75 degrees.",
        )

        assert response.transcription.text == "What is the weather?"
        assert "sunny" in response.full_response
        assert "sunny" in response.voice_response
        assert response.conversation_id is None

    def test_voice_chat_response_with_conversation_id(self) -> None:
        """Test VoiceChatResponse with conversation_id."""
        transcription = TranscriptionResult(
            text="Hello",
            provider=STTProvider.OPENAI_WHISPER,
        )

        response = VoiceChatResponse(
            transcription=transcription,
            full_response="Hi there!",
            voice_response="Hi there!",
            conversation_id="conv-123",
        )

        assert response.conversation_id == "conv-123"

    def test_voice_chat_response_different_full_and_voice(self) -> None:
        """Test that full_response and voice_response can differ."""
        transcription = TranscriptionResult(
            text="Explain quantum computing",
            provider=STTProvider.OPENAI_WHISPER,
        )

        full = (
            "Quantum computing is a type of computation that harnesses quantum "
            "mechanical phenomena such as superposition and entanglement. "
            "Unlike classical computers that use bits (0 or 1), quantum computers "
            "use quantum bits or qubits that can exist in multiple states simultaneously."
        )
        voice = "Quantum computing uses quantum physics to process information faster than regular computers."

        response = VoiceChatResponse(
            transcription=transcription,
            full_response=full,
            voice_response=voice,
        )

        assert len(response.full_response) > len(response.voice_response)
        assert "qubits" in response.full_response
        assert "qubits" not in response.voice_response
