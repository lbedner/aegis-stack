"""How the assistant hears and speaks, as rows the app changes.

Like the active model (``llm_active_selection``), a voice is table data:
switching or editing it takes effect on the next thing said, with no
``.env`` edit and no restart. ``.env`` only seeds the first profile.
"""

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.core.time import utcnow
from app.core.voice_settings import (
    LIVE_IDLE_MAX_SECONDS,
    TTS_SPEED_MAX,
    TTS_SPEED_MIN,
    setting_default,
)

from .live_engine import KEY_LENGTH


class VoiceProfile(SQLModel, table=True):
    """One named way of hearing and speaking; exactly one is active."""

    __tablename__ = "voice_profile"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    is_active: bool = Field(default=False, index=True)
    # Hearing.
    stt_provider: str = Field(default=setting_default("STT_PROVIDER"))
    stt_model: str | None = None
    # Speaking. ``tts_instructions`` is OpenAI's labeled delivery text
    # (Voice Affect, Tone, Emotion, Pronunciation, Pauses, Pacing).
    tts_provider: str = Field(default=setting_default("TTS_PROVIDER"))
    tts_model: str | None = None
    tts_voice: str | None = None
    tts_speed: float = Field(
        default=setting_default("TTS_SPEED"), ge=TTS_SPEED_MIN, le=TTS_SPEED_MAX
    )
    tts_instructions: str | None = None
    # How a spoken turn's reply is heard, and what plays while it works.
    reply: str = Field(default=setting_default("VOICE_REPLY"))
    working_sound: str = Field(default=setting_default("VOICE_WORKING_SOUND"))
    # A live call hangs up after this many seconds of dead air (0: never).
    live_idle_seconds: int = Field(
        default=setting_default("VOICE_LIVE_IDLE_SECONDS"),
        ge=0,
        le=LIVE_IDLE_MAX_SECONDS,
    )
    # Which engine a live call runs on (``voice/live_engines.py``).
    live_engine: str = Field(
        default=setting_default("VOICE_LIVE_ENGINE"), max_length=KEY_LENGTH
    )
    updated_at: datetime = Field(default_factory=utcnow)
