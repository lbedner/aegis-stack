"""
Voice module data models.

Defines the core data structures for Speech-to-Text transcription,
audio input handling, and voice chat responses.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.core.voice_settings import TTS_SPEED_MAX, TTS_SPEED_MIN, setting_default


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

    MARIN = "marin"
    CEDAR = "cedar"
    ALLOY = "alloy"  # Neutral, balanced voice
    ASH = "ash"
    BALLAD = "ballad"
    CORAL = "coral"
    SAGE = "sage"
    VERSE = "verse"
    ECHO = "echo"  # Warm, friendly voice
    FABLE = "fable"  # British-accented, narrative voice
    ONYX = "onyx"  # Deep, authoritative voice
    NOVA = "nova"  # Energetic, youthful voice
    SHIMMER = "shimmer"  # Clear, expressive voice


# What speaks and hears when nothing names a model or voice: one home for
# the TTS and STT configs, their providers, the catalog and the settings
# response.
DEFAULT_TTS_PROVIDER = TTSProvider(setting_default("TTS_PROVIDER"))
DEFAULT_STT_PROVIDER = STTProvider(setting_default("STT_PROVIDER"))
DEFAULT_TTS_MODEL = "tts-1"
DEFAULT_TTS_VOICE = OpenAIVoice.ALLOY.value
DEFAULT_STT_MODEL = "whisper-1"
# Each provider's model when none is named.
DEFAULT_STT_MODELS: dict[STTProvider, str] = {
    STTProvider.OPENAI_WHISPER: DEFAULT_STT_MODEL,
    STTProvider.GROQ_WHISPER: "whisper-large-v3-turbo",
    STTProvider.WHISPER_LOCAL: "openai/whisper-base",
    STTProvider.FASTER_WHISPER: "base",
}
# The setting holding each cloud provider's key; a provider not here runs
# locally and needs none.
TTS_KEYS: dict[TTSProvider, str] = {TTSProvider.OPENAI: "OPENAI_API_KEY"}
STT_KEYS: dict[STTProvider, str] = {
    STTProvider.OPENAI_WHISPER: "OPENAI_API_KEY",
    STTProvider.GROQ_WHISPER: "GROQ_API_KEY",
}


class AudioFormat(str, Enum):
    """Supported audio formats for transcription."""

    WAV = "wav"
    MP3 = "mp3"
    M4A = "m4a"
    WEBM = "webm"
    OGG = "ogg"
    FLAC = "flac"
    MP4 = "mp4"  # Audio track extraction

    @classmethod
    def of(cls, filename: str | None) -> AudioFormat | None:
        """The format a file's name says, when it is one taken here."""
        try:
            return cls((filename or "").rsplit(".", 1)[-1].lower())
        except ValueError:
            return None


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
    prompt: str | None = Field(
        default=None,
        description="Spelling hint for names the model cannot guess",
    )
    duration_seconds: float | None = Field(
        default=None,
        description="Duration of audio in seconds (optional, for usage tracking)",
    )
    prompt: str | None = Field(
        default=None,
        description="Spelling hint for names the model cannot guess",
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
    speed: float | None = Field(
        default=None,
        ge=TTS_SPEED_MIN,
        le=TTS_SPEED_MAX,
        description="Speech speed multiplier; None = TTS_SPEED",
    )
    instructions: str | None = Field(
        default=None,
        description="How to say it - tone, emotion, pacing (gpt-4o models); "
        "None = TTS_INSTRUCTIONS",
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

    tts_provider: str = DEFAULT_TTS_PROVIDER.value
    tts_model: str = DEFAULT_TTS_MODEL
    tts_voice: str = DEFAULT_TTS_VOICE
    tts_speed: float = setting_default("TTS_SPEED")
    stt_provider: str = DEFAULT_STT_PROVIDER.value
    stt_model: str = DEFAULT_STT_MODEL
    stt_language: str | None = None


class VoiceSettingsUpdate(BaseModel):
    """Voice settings update request (partial update)."""

    tts_provider: str | None = Field(None, description="TTS provider ID")
    tts_model: str | None = Field(None, description="TTS model ID")
    tts_voice: str | None = Field(None, description="TTS voice ID")
    tts_speed: float | None = Field(
        None, ge=TTS_SPEED_MIN, le=TTS_SPEED_MAX, description="TTS speed"
    )
    stt_provider: str | None = Field(None, description="STT provider ID")
    stt_model: str | None = Field(None, description="STT model ID")
    stt_language: str | None = Field(None, description="STT language code (e.g., 'en')")


class VoicePreviewRequest(BaseModel):
    """Voice preview generation request."""

    voice_id: str = Field(..., description="Voice ID to preview")
    text: str | None = Field(None, description="Custom text (uses default if None)")


# OpenAI's speech models that take delivery ``instructions`` (and every
# voice); their dated builds can be pinned (the March one is more
# expressive, the December one mishears less).
INSTRUCTED_TTS_MODELS = [
    "gpt-4o-mini-tts",
    "gpt-4o-mini-tts-2025-03-20",
    "gpt-4o-mini-tts-2025-12-15",
]
