"""
Voice module data models.

Defines the core data structures for Speech-to-Text transcription,
audio input handling, and voice chat responses.
"""

from enum import Enum

from pydantic import BaseModel, Field


class STTProvider(str, Enum):
    """Supported Speech-to-Text providers."""

    OPENAI_WHISPER = "openai_whisper"  # OpenAI Whisper API
    WHISPER_LOCAL = "whisper_local"  # Local Whisper via HuggingFace transformers
    FASTER_WHISPER = "faster_whisper"  # SYSTRAN faster-whisper (optimized local)
    GROQ_WHISPER = "groq_whisper"  # Groq API (ultra-fast)


class TTSProvider(str, Enum):
    """Supported Text-to-Speech providers."""

    OPENAI = "openai"  # OpenAI TTS API


class OpenAIVoice(str, Enum):
    """Available OpenAI TTS voices."""

    ALLOY = "alloy"  # Neutral, balanced voice
    ECHO = "echo"  # Warm, friendly voice
    FABLE = "fable"  # British-accented, narrative voice
    ONYX = "onyx"  # Deep, authoritative voice
    NOVA = "nova"  # Energetic, youthful voice
    SHIMMER = "shimmer"  # Clear, expressive voice


class AudioFormat(str, Enum):
    """Supported audio formats for transcription."""

    WAV = "wav"
    MP3 = "mp3"
    M4A = "m4a"
    WEBM = "webm"
    OGG = "ogg"
    FLAC = "flac"
    MP4 = "mp4"  # Audio track extraction


class AudioInput(BaseModel):
    """Input audio for transcription."""

    content: bytes = Field(..., description="Raw audio bytes")
    format: AudioFormat = Field(
        default=AudioFormat.WAV, description="Audio format (wav, mp3, m4a, webm, etc.)"
    )
    sample_rate: int | None = Field(
        default=None, description="Sample rate in Hz (optional)"
    )
    language: str | None = Field(
        default=None,
        description="ISO 639-1 language code (e.g., 'en', 'es'). If None, auto-detect.",
    )
    duration_seconds: float | None = Field(
        default=None,
        description="Duration of audio in seconds (optional, for usage tracking)",
    )

    model_config = {"arbitrary_types_allowed": True}


class TranscriptionSegment(BaseModel):
    """A segment of transcribed audio with timing information."""

    text: str = Field(..., description="Transcribed text for this segment")
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    confidence: float | None = Field(
        default=None, description="Confidence score (0-1) if available"
    )


class TranscriptionResult(BaseModel):
    """Result of STT transcription."""

    text: str = Field(..., description="Full transcribed text")
    language: str | None = Field(
        default=None, description="Detected or specified language code"
    )
    duration_seconds: float | None = Field(
        default=None, description="Audio duration in seconds"
    )
    confidence: float | None = Field(
        default=None, description="Overall confidence score (0-1) if available"
    )
    provider: STTProvider = Field(..., description="Provider used for transcription")
    segments: list[TranscriptionSegment] | None = Field(
        default=None, description="Word/phrase-level segments with timing"
    )


class SpeechRequest(BaseModel):
    """Input for TTS synthesis."""

    text: str = Field(..., description="Text to synthesize into speech")
    voice: str | None = Field(
        default=None, description="Voice ID to use (provider-specific)"
    )
    language: str | None = Field(
        default=None, description="Language code for synthesis"
    )
    speed: float = Field(
        default=1.0,
        ge=0.25,
        le=4.0,
        description="Speech speed multiplier (0.25 to 4.0)",
    )


class SpeechResult(BaseModel):
    """Result of TTS synthesis."""

    audio: bytes = Field(..., description="Synthesized audio data")
    format: AudioFormat = Field(..., description="Audio format of the output")
    duration_seconds: float | None = Field(
        default=None, description="Duration of the audio in seconds"
    )
    provider: TTSProvider = Field(..., description="Provider used for synthesis")

    model_config = {"arbitrary_types_allowed": True}


class VoiceChatResponse(BaseModel):
    """Response from voice chat with both full and voice-optimized versions."""

    transcription: TranscriptionResult = Field(
        ..., description="The transcription of what the user said"
    )
    full_response: str = Field(..., description="Full AI agent response")
    voice_response: str = Field(
        ...,
        description="Voice-optimized response (summarized if voice_mode=True, "
        "otherwise same as full_response)",
    )
    conversation_id: str | None = Field(
        default=None, description="Conversation ID for continuity"
    )
    audio_response: bytes | None = Field(
        default=None, description="TTS audio of the response (if return_audio=True)"
    )

    model_config = {"arbitrary_types_allowed": True}


# =============================================================================
# Voice Catalog Models
# =============================================================================


class VoiceCategory(str, Enum):
    """Voice personality/style categories."""

    NEUTRAL = "neutral"
    WARM = "warm"
    ENERGETIC = "energetic"
    AUTHORITATIVE = "authoritative"
    EXPRESSIVE = "expressive"


class ProviderInfo(BaseModel):
    """Information about a voice provider (TTS or STT)."""

    id: str = Field(..., description="Provider identifier (e.g., 'openai')")
    name: str = Field(..., description="Display name (e.g., 'OpenAI')")
    type: str = Field(..., description="Provider type: 'tts' or 'stt'")
    requires_api_key: bool = Field(
        default=True, description="Whether this provider requires an API key"
    )
    api_key_env_var: str | None = Field(
        default=None, description="Environment variable name for API key"
    )
    is_local: bool = Field(
        default=False, description="Whether this is a local/offline provider"
    )
    description: str | None = Field(default=None, description="Provider description")


class ModelInfo(BaseModel):
    """Information about a voice model."""

    id: str = Field(..., description="Model identifier (e.g., 'tts-1')")
    name: str = Field(..., description="Display name (e.g., 'TTS-1')")
    provider_id: str = Field(..., description="Provider this model belongs to")
    quality: str = Field(
        default="standard", description="Quality tier: 'standard', 'hd', 'turbo'"
    )
    description: str | None = Field(default=None, description="Model description")
    supports_streaming: bool = Field(
        default=False, description="Whether this model supports streaming"
    )
    max_input_chars: int | None = Field(
        default=None, description="Maximum input characters for TTS"
    )


class VoiceInfo(BaseModel):
    """Information about a voice option."""

    id: str = Field(..., description="Voice identifier (e.g., 'alloy')")
    name: str = Field(..., description="Display name (e.g., 'Alloy')")
    provider_id: str = Field(..., description="Provider this voice belongs to")
    model_ids: list[str] = Field(
        default_factory=list, description="Compatible model IDs"
    )
    description: str = Field(..., description="Voice description")
    category: VoiceCategory | None = Field(
        default=None, description="Voice personality category"
    )
    gender: str | None = Field(
        default=None, description="Voice gender: 'male', 'female', 'neutral'"
    )
    preview_text: str = Field(
        default="Hello, I'm {voice_name}. How can I help you today?",
        description="Default text for voice preview",
    )


class VoiceSettingsResponse(BaseModel):
    """Current voice settings response."""

    tts_provider: str = "openai"
    tts_model: str = "tts-1"
    tts_voice: str = "alloy"
    tts_speed: float = 1.0
    stt_provider: str = "openai_whisper"
    stt_model: str = "whisper-1"
    stt_language: str | None = None


class VoiceSettingsUpdate(BaseModel):
    """Voice settings update request (partial update)."""

    tts_provider: str | None = Field(None, description="TTS provider ID")
    tts_model: str | None = Field(None, description="TTS model ID")
    tts_voice: str | None = Field(None, description="TTS voice ID")
    tts_speed: float | None = Field(
        None, ge=0.25, le=4.0, description="TTS speed (0.25-4.0)"
    )
    stt_provider: str | None = Field(None, description="STT provider ID")
    stt_model: str | None = Field(None, description="STT model ID")
    stt_language: str | None = Field(None, description="STT language code (e.g., 'en')")


class VoicePreviewRequest(BaseModel):
    """Voice preview generation request."""

    voice_id: str = Field(..., description="Voice ID to preview")
    text: str | None = Field(None, description="Custom text (uses default if None)")
