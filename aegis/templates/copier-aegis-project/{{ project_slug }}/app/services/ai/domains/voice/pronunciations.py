"""How terms are said, saved as rows over the list in code (``spoken``).
Each change puts the saved rows to work at once, so the next thing said in
this process says it; anything else loads them where it reads its voice
(``profiles``)."""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.ai.domains.voice import queries, spoken
from app.services.ai.models.voice import VoicePronunciation
from app.services.ai.models.voice.pronunciation import TERM_LENGTH

NEEDS_BOTH = "A term needs how it is said."
TOO_LONG = f"A term is at most {TERM_LENGTH} characters."

saved = queries.pronunciations


class PronunciationError(ValueError):
    """A pronunciation that cannot be saved."""


async def load(session: AsyncSession) -> None:
    """Put the saved rows to work over the list in code."""
    spoken.use_saved(
        spoken.Pronunciation(term=row.term, say=row.say, ipa=row.ipa)
        for row in await saved(session)
    )


async def save(
    session: AsyncSession, term: str, say: str, ipa: str | None = None
) -> None:
    """Say ``term`` as ``say`` from the next thing said: a new row, or the
    row already saved for that term changed."""
    term, say, ipa = term.strip(), say.strip(), (ipa or "").strip() or None
    if not term or not say:
        raise PronunciationError(NEEDS_BOTH)
    if len(term) > TERM_LENGTH:
        raise PronunciationError(TOO_LONG)
    key = spoken.term_key(term)
    row = await queries.pronunciation_of(session, key)
    if row is None:
        row = VoicePronunciation(key=key, term=term, say=say, ipa=ipa)
    else:
        row.term, row.say, row.ipa, row.updated_at = term, say, ipa, utcnow()
    session.add(row)
    await session.commit()
    await load(session)


async def remove(session: AsyncSession, term: str) -> None:
    """Drop ``term``'s saved row: it is said the way the code says it
    again, or as written."""
    row = await queries.pronunciation_of(session, spoken.term_key(term))
    if row is not None:
        await session.delete(row)
        await session.commit()
    await load(session)
