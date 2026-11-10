"""What a picture shared in chat showed, kept and read on demand.

A picture rides one model call as bytes (``attachments``) and history
replays as text, so the turn after it the assistant had forgotten what
the screenshot showed. The attachment marker now names each picture by a
handle taken from its storage key; on the worker (``read_photo_job``) the
picture gets a line in the user's paste index (``agent_user_memory``,
beside the facts and the readings, so it reaches the next conversation
too) and what it showed is read once and kept beside it. ``pasted`` reads
the reading back in any later turn.
"""

from datetime import UTC, datetime

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_async_session
from app.core.figures import FIGURES
from app.core.storage import get_storage
from app.core.tools import register_tool
from app.services.ai.domains.chat.user_memory import current_user_id, get_user_memory
from app.services.ai.models.agents import AgentUserMemory

# The index is a line each; the bytes live in storage. Bounded anyway, so
# a year of screenshots cannot grow the row without limit.
MAX_PASTES_PER_USER = 50

# Short enough for a model to quote back without fumbling it, long enough
# that two pictures will not collide.
ID_LENGTH = 8

# What ``pasted`` says of a picture before its reading has landed. The
# turn that carries the picture names it too, and there the bytes are
# right beside the marker: asking again would only cost a round trip.
PICTURE_UNREAD = (
    "(no reading on file yet: a picture is read just after it is shared, "
    "where a model that can see is in force. If the picture is attached to "
    "this turn, look at it directly; do not ask for it again in this turn)"
)

# How a shared picture is read, and where its usage is recorded: apart
# from paper read for the documents service.
PICTURE_SURFACE = "chat:picture"
PICTURE_READING = (
    "You are shown a picture someone shared in a conversation: a "
    "screenshot, a photo of paper, or something on their screen. Start "
    "with one sentence saying what it is. Then give every piece of legible "
    "text on it in reading order, keeping amounts, dates, names and numbers "
    "exactly as shown; a table one row per line, cells separated by ' | '. "
    "Do not interpret or add anything that is not in the picture."
)


class Picture(BaseModel):
    """A picture kept from chat, as its line in the paste index."""

    model_config = FIGURES

    id: str
    key: str
    media_type: str
    title: str
    at: str = ""
    reading_key: str | None = None


def paste_id(key: str) -> str:
    """The handle the agent uses, from the storage key: the digest's first
    characters, since a model asked to repeat a 78-character key will
    hallucinate one."""
    return key.rsplit("/", 1)[-1][:ID_LENGTH]


async def pictures_of(session: AsyncSession, user_id: str) -> list[Picture]:
    """The pictures this user has on file, oldest first."""
    row = await get_user_memory(session, user_id)
    return [Picture(**p) for p in row.memory.get("pastes", [])] if row else []


async def keep_picture(
    session: AsyncSession, user_id: str, picture: Picture
) -> Picture:
    """Keep ``picture`` in the user's index, newest last, one per id: the
    same bytes again are the same line, keeping what was learned of them
    (its reading). The index's one writer; the line as kept."""
    row = await get_user_memory(session, user_id) or AgentUserMemory(user_id=user_id)
    index = [Picture(**p) for p in row.memory.get("pastes", [])]
    known = next((p for p in index if p.id == picture.id), None)
    kept = picture.model_copy(
        update={
            "at": datetime.now(UTC).isoformat(),
            "reading_key": picture.reading_key
            or (known.reading_key if known else None),
        }
    )
    index = [p for p in index if p.id != picture.id] + [kept]
    row.memory = {
        **row.memory,
        "pastes": [p.model_dump() for p in index[-MAX_PASTES_PER_USER:]],
    }
    session.add(row)
    return kept


async def read_picture(image: bytes, media_type: str) -> str | None:
    """What a picture shows, read with the documents service's vision, or
    None where no model that can see is in force."""
    from app.services.documents import service as documents

    if await documents.vision_reader() is None:
        return None
    text, _model = await documents.look(
        image,
        media_type,
        instructions=PICTURE_READING,
        ask="What does this picture show?",
        surface=PICTURE_SURFACE,
    )
    return text


async def pasted(paste_id: str) -> str:
    """Read back what a picture the user shared showed.

    A picture rides only the turn it was shared in; its marker names its
    id. Call this with that id whenever a later turn needs what it
    showed, rather than trying to remember it: the reading is kept, and
    outlives the conversation it was shared in.
    """
    user_id = current_user_id.get()
    if not user_id:
        return "No user context available; cannot read that picture."
    async with get_async_session() as session:
        index = await pictures_of(session, user_id)
    picture = next((p for p in index if p.id == paste_id), None)
    if picture is None:
        known = ", ".join(p.id for p in index) or "none"
        return f"No picture {paste_id!r} on file. {PICTURE_UNREAD} On file: {known}."
    reading = picture.reading_key and await get_storage().get(picture.reading_key)
    return reading.decode("utf-8", errors="replace") if reading else PICTURE_UNREAD


# Built-in registration: importing this module makes the tool grantable
# via the agent registry. replace=True keeps re-imports idempotent.
register_tool(
    "pasted",
    pasted,
    description="Read back what a picture the user shared showed",
    effect="read",
    replace=True,
)
