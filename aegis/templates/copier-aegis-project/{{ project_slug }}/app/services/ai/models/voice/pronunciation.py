"""How a term is said, as rows saved over the list in code
(``domains/voice/spoken``)."""

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.core.time import utcnow

TERM_LENGTH = 100


class VoicePronunciation(SQLModel, table=True):
    """One term and how every voice says it, one row per ``key``
    (``spoken.term_key``)."""

    __tablename__ = "voice_pronunciation"

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(unique=True, index=True, max_length=TERM_LENGTH)
    term: str = Field(max_length=TERM_LENGTH)
    say: str = Field(max_length=200)
    ipa: str | None = Field(default=None, max_length=200)
    updated_at: datetime = Field(default_factory=utcnow)
