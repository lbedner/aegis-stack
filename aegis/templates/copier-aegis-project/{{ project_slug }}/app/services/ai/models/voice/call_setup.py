"""How a call runs, as a row the app changes.

What a call is made of - the live engine, or the chain's hearing and
speaking models - and how it behaves: how a reply is heard, what plays while
it works, when it checks in. One row: picking a model changes it and never
the voice (``VoiceProfile``, how she sounds). ``.env`` only seeds it.
"""

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.core.time import utcnow
from app.core.voice_settings import LIVE_IDLE_MAX_SECONDS, setting_default

from .live_engine import KEY_LENGTH


class CallSetup(SQLModel, table=True):
    """What a call runs on and how it behaves; there is one."""

    __tablename__ = "call_setup"

    id: int | None = Field(default=None, primary_key=True)
    # Hearing.
    stt_provider: str = Field(default=setting_default("STT_PROVIDER"))
    stt_model: str | None = None
    # Speaking, on the chain and for spoken replies: the voice it speaks in
    # is the active profile's for this provider (``VoiceProfile.voices``).
    tts_provider: str = Field(default=setting_default("TTS_PROVIDER"))
    tts_model: str | None = None
    # How a spoken turn's reply is heard, and what plays while it works.
    reply: str = Field(default=setting_default("VOICE_REPLY"))
    working_sound: str = Field(default=setting_default("VOICE_WORKING_SOUND"))
    # Seconds of quiet on a live call before the assistant checks in
    # (VOICE_LIVE_IDLE_SECONDS).
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
