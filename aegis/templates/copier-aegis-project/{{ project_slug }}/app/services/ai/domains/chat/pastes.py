"""What was pasted or shared in chat, kept once and read on demand.

A pasted page (an order listing, a log, a spreadsheet dump) used to be
message text, and history REPLAYS: the same page rode every later turn
until the budget pushed it out, and on screen the conversation vanished
into it. A wall of text (``PASTE_THRESHOLD``) now goes to the object store
(content-addressed, so pasting it twice is free) and a one-line marker
(``chat_transcript.paste_marker``) stands where it was; the composer keeps
one as it is pasted, and the turn lifts any it still carries (``lift_walls``).
A line pushed out of the index takes its bytes with it, where nothing else
names them.

An attached PDF, where the documents service reads one, lands in the same
index: its pages stay where extraction put them (one home) and the line
points at the document. A picture's bytes ride one model call; on the
worker (``read_photo_job``) it gets a line here and what it showed is read
once and kept beside it.

The index is a line each in the user's ``agent_user_memory`` row, beside
the facts and the readings, so a paste reaches the next conversation too.
``pasted`` reads any of them back: the marker, the tool and the chip do
not care which kind it is.
"""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.chat_transcript import IMAGE_TYPES, paste_ids, paste_marker
from app.core.db import get_async_session, release_lock
from app.core.figures import FIGURES
from app.core.log import logger
from app.core.storage import get_storage, held
from app.core.tools import current_owner_user_id, register_tool
from app.services.ai.domains.chat.attachments import PASTE_THRESHOLD, ChatAttachment
from app.services.ai.domains.chat.user_memory import current_user_id, get_user_memory
from app.services.ai.models.agents import AgentUserMemory

# The index is a line each; the bytes live in storage. Bounded anyway, so
# a year of pasting cannot grow the row without limit.
MAX_PASTES_PER_USER = 50

# Short enough for a model to quote back without fumbling it, long enough
# that two pastes will not collide.
ID_LENGTH = 8

# How each page of a document reads back.
PAGE_HEADING = "--- page {number} ---\n"

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


class Paste(BaseModel):
    """A line of the paste index: a wall of text (its bytes at ``key``), a
    read document (its pages at ``document_id``), or a picture (its bytes
    at ``key``, what it showed at ``reading_key``)."""

    model_config = FIGURES

    id: str
    title: str
    key: str | None = None
    media_type: str = "text/plain"
    chars: int = 0
    document_id: int | None = None
    at: str = ""
    reading_key: str | None = None

    @property
    def is_picture(self) -> bool:
        return self.media_type in IMAGE_TYPES

    @property
    def marker(self) -> str:
        """What stands in the message for it."""
        return paste_marker(self.id, self.title, self.chars)


def paste_id(key: str) -> str:
    """The handle the agent uses, from the storage key: the digest's first
    characters, since a model asked to repeat a 78-character key will
    hallucinate one."""
    return key.rsplit("/", 1)[-1][:ID_LENGTH]


async def pastes_of(session: AsyncSession, user_id: str) -> list[Paste]:
    """What this user has on file, oldest first."""
    row = await get_user_memory(session, user_id)
    return [Paste(**p) for p in row.memory.get("pastes", [])] if row else []


async def keep_pastes(
    session: AsyncSession, user_id: str, pastes: Sequence[Paste]
) -> list[Paste]:
    """Keep ``pastes`` in the user's index, newest last, one per id: the
    same bytes again are the same line, keeping what was learned of them
    (a picture's reading). The index's one writer; the index as kept."""
    row = await get_user_memory(session, user_id) or AgentUserMemory(user_id=user_id)
    index = [Paste(**p) for p in row.memory.get("pastes", [])]
    at = datetime.now(UTC).isoformat()
    for paste in pastes:
        known = next((p for p in index if p.id == paste.id), None)
        kept = paste.model_copy(
            update={
                "at": at,
                "reading_key": paste.reading_key
                or (known.reading_key if known else None),
            }
        )
        index = [p for p in index if p.id != paste.id] + [kept]
    dropped, index = index[:-MAX_PASTES_PER_USER], index[-MAX_PASTES_PER_USER:]
    row.memory = {**row.memory, "pastes": [p.model_dump() for p in index]}
    session.add(row)
    if dropped:
        await session.flush()
        await _let_go(session, dropped)
    return index


async def keep_paste(session: AsyncSession, user_id: str, paste: Paste) -> Paste:
    """``keep_pastes`` for one: its line, as kept."""
    return (await keep_pastes(session, user_id, [paste]))[-1]


async def _let_go(session: AsyncSession, dropped: list[Paste]) -> None:
    """Delete the bytes the lines pushed out of the index named, where no
    row names them still (``held``): content-addressed, the same page
    someone else pasted is the same bytes, and a picture's are its
    message's attachment. A document's pages are the documents service's.

    ponytail: one ``held`` read per key, as a paste pushes one line out
    (batch it if a pass drops many); and before the commit, so a trim the
    caller then rolls back keeps a line whose bytes are gone (it reads as
    missing, never as someone else's)."""
    storage = get_storage()
    for key in (k for p in dropped for k in (p.key, p.reading_key) if k):
        try:
            if not await held(session, key):
                await storage.delete(key)
        except OSError as exc:
            logger.warning(f"Could not delete a dropped paste's bytes: {exc}")


def title_of(block: str) -> str:
    """A name for a wall of text: its first line that says anything. Pages
    open with navigation ("All", "Cart"), so a line of one short word is
    skipped while a real heading ("Your Orders") still wins."""
    for line in block.splitlines():
        line = line.strip()
        if len(line) > 8:
            return line[:60]
    return "pasted text"


async def _put(text: str) -> Paste:
    """A wall of text in the store: its line, not yet kept."""
    key = await get_storage().put(text.encode("utf-8"), content_type="text/plain")
    return Paste(id=paste_id(key), key=key, title=title_of(text), chars=len(text))


async def store_paste(session: AsyncSession, user_id: str, text: str) -> Paste:
    """Keep a wall of text for this user: its line, as kept."""
    return await keep_paste(session, user_id, await _put(text))


async def lift_walls(
    session: AsyncSession, user_id: str, text: str, read: Sequence[Paste] = ()
) -> tuple[str, list[Paste]]:
    """``text`` with each wall of text in it kept and standing as its
    marker, and every paste its markers name (one the composer kept as it
    was pasted, too), once each, in order. ``read`` are lines this turn
    read already (an attached document's), kept in the same pass.

    The unit is a block (blank lines are where a paste meets what someone
    wrote), so the sentence introducing a page stays, and a long message
    of paragraphs someone typed is left alone. A store that refuses leaves
    the wall in place: the paste must land somewhere, and in the message
    is where every paste used to."""
    blocks = text.split("\n\n")
    walls: list[Paste] = []
    for at, block in enumerate(blocks):
        if len(block) <= PASTE_THRESHOLD:
            continue
        try:
            walls.append(await _put(block))
        except OSError as exc:
            logger.warning(f"Could not store pasted text: {exc}")
            continue
        blocks[at] = walls[-1].marker
    text = "\n\n".join(blocks)
    wanted = list(dict.fromkeys(paste_ids(text)))
    kept = [*walls, *read]
    if not (wanted or kept):
        return text, []
    index = await (
        keep_pastes(session, user_id, kept) if kept else pastes_of(session, user_id)
    )
    found = {p.id: p for p in index}
    return text, [found[i] for i in wanted if i in found]


async def read_documents(
    session: AsyncSession,
    attached: Sequence[ChatAttachment],
    owner_user_id: int | None = None,
) -> list[Paste | BaseException | None]:
    """Read attached documents into the documents service: each one's line,
    not yet kept (``lift_walls`` keeps it), None when it gave no pages, or
    what stopped it (a parser over uploaded bytes). Same bytes again are the
    same document, its read pages read once. Their pages are read together,
    on the worker where the stack has one (``extract_and_wait``), with no
    transaction held while they are."""
    from app.services.documents import service as documents

    ingested: list[int | BaseException] = []
    for attachment in attached:
        try:
            document = await documents.DocumentService(session).ingest(
                attachment.decoded(),
                title=attachment.name or "document",
                media_type=attachment.media_type,
                owner_user_id=owner_user_id,
                source="chat",
            )
            ingested.append(int(document.id or 0))
            await release_lock(session)
        except Exception as exc:  # noqa: BLE001 - one file's failure is its own
            await session.rollback()
            ingested.append(exc)
    waits = iter(
        await asyncio.gather(
            *(
                documents.extract_and_wait(i, owner_user_id=owner_user_id, force=False)
                for i in ingested
                if isinstance(i, int)
            ),
            return_exceptions=True,
        )
    )
    found: list[Paste | BaseException | None] = []
    for attachment, document_id in zip(attached, ingested, strict=True):
        if isinstance(document_id, BaseException):
            found.append(document_id)
            continue
        if isinstance(waited := next(waits), BaseException):
            found.append(waited)
            continue
        text = await document_text(session, document_id, owner_user_id)
        found.append(
            Paste(
                id=f"{document_id:08x}"[-ID_LENGTH:],
                title=attachment.name or "document",
                media_type=attachment.media_type,
                chars=len(text),
                document_id=document_id,
            )
            if text
            else None
        )
    return found


async def document_text(
    session: AsyncSession, document_id: int, owner_user_id: int | None
) -> str | None:
    """Every page of a document in order, as one text, or None when it has
    none ``owner_user_id`` may read. A page that could not be read says so
    with its reason: the agent must be able to tell a page that said
    nothing from one nobody could read."""
    from app.services.documents import service as documents

    pages = await documents.pages_for(session, document_id, owner_user_id=owner_user_id)
    parts = [
        PAGE_HEADING.format(number=page.page_number)
        + (
            page.text.strip()
            if page.status == "read" and page.text
            else f"[page {page.page_number} could not be read: "
            f"{page.detail or 'no text'}]"
        )
        for page in pages
    ]
    return "\n\n".join(parts).strip() or None


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


async def read_paste(
    session: AsyncSession, user_id: str, paste_id: str, *, owner_user_id: int | None
) -> tuple[Paste, str] | None:
    """A paste's line and what it holds, or None when this user has no such
    paste, its bytes are gone, or it is a document ``owner_user_id`` (the
    turn's owner) may not read: the index is the chat user's, the pages
    their document's owner's. The one lookup: ``pasted`` is the agent's
    door onto it and the chip's dialog the reader's. No transaction is
    held while the bytes are fetched."""
    index = await pastes_of(session, user_id)
    paste = next((p for p in index if p.id == paste_id), None)
    pages = (
        await document_text(session, paste.document_id, owner_user_id)
        if paste is not None and paste.document_id is not None
        else None
    )
    await release_lock(session)
    if paste is None:
        return None
    if paste.document_id is not None:
        text = pages
    elif paste.is_picture:
        text = await _blob(paste.reading_key) or PICTURE_UNREAD
    else:
        text = await _blob(paste.key)
    if text is None:
        logger.warning("paste index points at missing bytes", paste_id=paste_id)
        return None
    return paste, text


async def _blob(key: str | None) -> str | None:
    data = await get_storage().get(key) if key else None
    return data.decode("utf-8", errors="replace") if data is not None else None


async def pasted(paste_id: str) -> str:
    """Read back a block of text the user pasted, a document they
    attached, or what a picture they shared showed.

    Each stands in the conversation as a one-line marker naming its id,
    because replaying a whole page into every later turn is what pushes
    the rest of the conversation out of your context. Call this with the
    id from the marker the moment you need the content, and again in a
    later turn rather than trying to remember it: it is kept, and outlives
    the conversation it was shared in.
    """
    user_id = current_user_id.get()
    if not user_id:
        return "No user context available; cannot read that paste."
    async with get_async_session() as session:
        found = await read_paste(
            session, user_id, paste_id, owner_user_id=current_owner_user_id.get()
        )
    if found is None:
        return f"No paste {paste_id!r} on file. {PICTURE_UNREAD}"
    return found[1]


# Built-in registration: importing this module makes the tool grantable
# via the agent registry. replace=True keeps re-imports idempotent.
register_tool(
    "pasted",
    pasted,
    description=(
        "Read back a pasted block of text, an attached document, or what a "
        "shared picture showed"
    ),
    effect="read",
    replace=True,
)
