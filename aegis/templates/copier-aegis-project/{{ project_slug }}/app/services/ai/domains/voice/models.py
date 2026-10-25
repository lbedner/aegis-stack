"""
Voice module data models.

Defines the core data structures for Speech-to-Text transcription,
audio input handling, and voice chat responses.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

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
    GEMINI = "gemini"  # Gemini's speech models, the voices Gemini Live speaks


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
# OpenAI's speech model: gpt-realtime-2.1-mini, the one it names for
# when every /v1/audio/speech model shuts down (Jan 6, 2027). It speaks
# over the Realtime API only (``tts/realtime.py``).
DEFAULT_TTS_MODEL = "gpt-realtime-2.1-mini"
REALTIME_TTS_MODELS = [DEFAULT_TTS_MODEL]
DEFAULT_TTS_VOICE = OpenAIVoice.ALLOY.value
# Each provider's model and voice when none is named.
DEFAULT_TTS_MODELS: dict[TTSProvider, str] = {
    TTSProvider.OPENAI: DEFAULT_TTS_MODEL,
    TTSProvider.GEMINI: "gemini-3.8-flash-tts",
}
DEFAULT_TTS_VOICES: dict[TTSProvider, str] = {
    TTSProvider.OPENAI: DEFAULT_TTS_VOICE,
    TTSProvider.GEMINI: "Kore",
}
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
TTS_KEYS: dict[TTSProvider, str] = {
    TTSProvider.OPENAI: "OPENAI_API_KEY",
    TTSProvider.GEMINI: "GOOGLE_API_KEY",
}
# The catalog org whose logo each speech provider shows (Gemini is Google's).
TTS_ORGS: dict[TTSProvider, str] = {
    TTSProvider.OPENAI: "openai",
    TTSProvider.GEMINI: "google",
}
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


# What each format is served as.
MEDIA_TYPES: dict[AudioFormat, str] = {
    AudioFormat.WAV: "audio/wav",
    AudioFormat.MP3: "audio/mpeg",
    AudioFormat.M4A: "audio/mp4",
    AudioFormat.WEBM: "audio/webm",
    AudioFormat.OGG: "audio/ogg",
    AudioFormat.FLAC: "audio/flac",
    AudioFormat.MP4: "audio/mp4",
}
# What each speaking provider's audio comes back as, known before a
# stream's first byte.
TTS_FORMATS: dict[TTSProvider, AudioFormat] = {
    TTSProvider.OPENAI: AudioFormat.MP3,
    TTSProvider.GEMINI: AudioFormat.WAV,
}


def speech_format(provider: TTSProvider, model: str) -> AudioFormat:
    """What a provider's model speaks in: a realtime model's PCM comes back
    as WAV, otherwise the provider's own format."""
    return AudioFormat.WAV if model in REALTIME_TTS_MODELS else TTS_FORMATS[provider]


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
        description="How to say it - tone, emotion, pacing (a model that "
        "steers them); "
        "None = TTS_INSTRUCTIONS",
    )


class SpeechTokens(BaseModel):
    """What a realtime model billed for a line, in the names Pydantic AI's
    ``RequestUsage`` gives a call's, so the ledger prices both alike
    (``spend.recording.realtime_cost``). Not that class itself: speech runs
    on LangChain stacks too, which have no Pydantic AI."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int = 0
    output_tokens: int = 0
    input_audio_tokens: int = 0
    output_audio_tokens: int = 0
    cache_read_tokens: int = 0


class SpeechResult(BaseModel):
    """Result of TTS synthesis."""

    audio: bytes = Field(..., description="Synthesized audio data")
    format: AudioFormat = Field(..., description="Audio format of the output")
    duration_seconds: float | None = Field(
        default=None, description="Duration of the audio in seconds"
    )
    provider: TTSProvider = Field(..., description="Provider used for synthesis")
    tokens: SpeechTokens | None = Field(
        default=None,
        description="What a realtime model billed; None for a model billed "
        "by the character or second",
    )

    model_config = {"arbitrary_types_allowed": True}

    @property
    def media_type(self) -> str:
        """What the audio is served as."""
        return MEDIA_TYPES[self.format]


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
    steers: list[str] = Field(
        default_factory=list,
        description="What its delivery instructions steer (accent, tone...); "
        "none for a model that ignores them",
    )
    retires: str | None = Field(
        default=None, description="When its provider shuts it down"
    )
    speeds: tuple[float, float] | None = Field(
        default=(TTS_SPEED_MIN, TTS_SPEED_MAX),
        description="The speeds it can be set to; None for one with no speed",
    )

    @property
    def note(self) -> str:
        """What it is, after when it shuts down where it does."""
        said = self.description or ""
        return f"Shuts down {self.retires}; {said}" if self.retires else said


class VoiceInfo(BaseModel):
    """Information about a voice option."""

    id: str = Field(..., description="Voice identifier (e.g., 'alloy')")
    name: str = Field(..., description="Display name (e.g., 'Alloy')")
    provider_id: str = Field(..., description="Provider this voice belongs to")
    model_ids: list[str] = Field(
        default_factory=list, description="Compatible model IDs"
    )
    description: str = Field(..., description="Voice description")
    gender: str | None = Field(
        default=None, description="Voice gender: 'male', 'female', 'neutral'"
    )
    tone: str | None = Field(
        default=None, description="How it sounds, in a word (Warm, Bright, Firm)"
    )
    accent: str | None = Field(
        default=None, description="The accent it speaks with (American, British)"
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
