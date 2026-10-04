"""Speech settings for ai[voice], kept out of config.py's size budget.

``Settings`` inherits these, so they read as ``settings.STT_MODEL`` and load
from ``.env`` like every other setting.
"""

from typing import Any, Literal

from pydantic import Field
from pydantic_settings import BaseSettings

# The speech speed the TTS API accepts, and the longest a live call may
# sit in dead air: every model, form and profile bounds by these.
TTS_SPEED_MIN, TTS_SPEED_MAX = 0.25, 4.0
LIVE_IDLE_MAX_SECONDS = 600


# How a spoken reply is heard, and what plays while the assistant works: the values
# the settings, a profile and its form all take.
Reply = Literal["live", "answer"]
WorkingSound = Literal["typing", "none"]


class VoiceSettings(BaseSettings):
    # Speech-to-Text (STT) Configuration
    # Provider: openai_whisper, whisper_local, faster_whisper, groq_whisper
    STT_PROVIDER: str = "openai_whisper"  # Default to OpenAI Whisper API
    STT_MODEL: str | None = None  # Model name/size (provider-specific, None = default)
    STT_LANGUAGE: str | None = None  # ISO 639-1 language code (None = auto-detect)
    # For local providers (whisper_local, faster_whisper)
    STT_DEVICE: str | None = None  # Device: 'cpu', 'cuda', 'mps' (None = auto-detect)

    # Text-to-Speech (TTS) Configuration
    # Provider: openai
    TTS_PROVIDER: str = "openai"  # Default to OpenAI TTS API
    TTS_MODEL: str | None = (
        None  # Model: tts-1 (fast), tts-1-hd (quality). None = default
    )
    TTS_VOICE: str | None = (
        None  # Voice: alloy, echo, fable, onyx, nova, shimmer. None = alloy
    )
    # Sent to the model as ``speed`` (it used to be read and never sent).
    TTS_SPEED: float = Field(default=1.0, ge=TTS_SPEED_MIN, le=TTS_SPEED_MAX)
    # How it is said - tone, emotion, pacing - sent as ``instructions``
    # (gpt-4o models only). OpenAI's documented way to steer delivery.
    TTS_INSTRUCTIONS: str | None = None

    # How a spoken turn's reply is heard. "live": each sentence as it
    # streams, narration included, as soon as it is complete. "answer": the
    # settled answer, once. A list, not a flag, so a later mode is one more
    # value rather than new plumbing.
    VOICE_REPLY: Reply = "live"
    # What plays while the assistant works and has said nothing yet: soft
    # generated key taps ("typing"), or nothing. Narrating its tool calls
    # instead ran behind its own answer.
    VOICE_WORKING_SOUND: WorkingSound = "typing"
    # A live call hangs up after this many seconds of dead air (0: never):
    # A live call bills while it is open, silence included.
    VOICE_LIVE_IDLE_SECONDS: int = Field(default=30, ge=0, le=LIVE_IDLE_MAX_SECONDS)
    # The engine a live call runs on: a key in voice/live_engines.py.
    VOICE_LIVE_ENGINE: str = "gemini-live"


def setting_default(name: str) -> Any:
    """A voice setting's own default, for what starts where ``.env`` would
    (a voice profile's columns, the default live engine)."""
    return VoiceSettings.model_fields[name].default
