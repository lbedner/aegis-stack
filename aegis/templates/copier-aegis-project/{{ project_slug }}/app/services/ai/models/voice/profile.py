"""How the assistant sounds, as rows the app changes.

Like the active model (``llm_active_selection``), a voice is table data:
switching or editing it takes effect on the next thing said, with no
``.env`` edit and no restart. ``.env`` only seeds the first profile. What a
call runs on is not the voice's: that is the call setup (``CallSetup``).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.core.time import utcnow
from app.core.voice_settings import TTS_SPEED_MAX, TTS_SPEED_MIN, setting_default


class VoiceProfile(SQLModel, table=True):
    """One named way of sounding; exactly one is active."""

    __tablename__ = "voice_profile"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    is_active: bool = Field(default=False, index=True)
    # Her voice on each engine that speaks: a TTS provider's id
    # (``TTSProvider``) -> a voice id of that provider's. The call setup's
    # speaking provider, or a live engine's vendor, picks the one heard.
    voices: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    tts_speed: float = Field(
        default=setting_default("TTS_SPEED"), ge=TTS_SPEED_MIN, le=TTS_SPEED_MAX
    )
    # OpenAI's labeled delivery text (Voice Affect, Tone, Emotion,
    # Pronunciation, Pauses, Pacing); a live call takes it as instructions.
    tts_instructions: str | None = None
    # The voice designer's choices those instructions were made from
    # (``domains/voice/delivery.Delivery``), so it opens on them again;
    # None for instructions written by hand.
    tts_delivery: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=utcnow)
