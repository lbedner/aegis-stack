"""Chat attachments: generic multimodal message parts.

One module owns the whole shape so every surface stays in step: the
wire model (``ChatAttachment``, what the API accepts, within the limits
``composer`` tells the browser), the model-call content
(``build_user_content``, what the agent actually sees) and the history
marker (``annotate_attachments``, what later turns know). Any agent on
any chat surface gets attachments by threading this module - nothing here
belongs to a particular service or screen.

A turn's text is lifted before the turn (``lift_turn``, in a session the
way in opens): a wall of pasted text, and an attached PDF where the
documents service reads one, stand in the message as a one-line marker
(``pastes``), read back on demand. The turn itself (``prepare_turn``)
opens no session.

The bytes ride the current turn only: history replays as text, so the
marker records that a screenshot was there without re-sending it every
turn. Whether the model can SEE the image is the model's own capability
(a vision-capable pick like a Qwen-VL class model); a text-only model
still receives the marker and can say so.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, field_validator

from app.core.chat_transcript import IMAGE_TYPES, MAX_ATTACHMENT_BYTES
from app.core.discovery import present
from app.core.log import logger
from app.core.storage import get_storage

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

# Where what is pasted can be kept apart from the message (``pastes``).
_KEEPS_PASTES = present("app.services.ai.domains.chat.pastes")
# Where a picture shared in chat can be kept and read.
_READABLE = (
    _KEEPS_PASTES
    and present("app.components.worker")
    and present("app.services.documents")
)
# A PDF is read, not shown to the model: the documents service takes its
# text layer (pypdfium2) and reads a scan's pages with vision. Without it
# a turn carries images only.
READS_PDF = _KEEPS_PASTES and present("app.services.documents")
DOCUMENT_TYPES = frozenset({"application/pdf"} if READS_PDF else ())
ACCEPTED_TYPES = IMAGE_TYPES | DOCUMENT_TYPES

# What one turn may carry: the request holds it, and the composer is told
# it (``composer``) so it refuses a file before it is sent. Each file's cap
# is ``MAX_ATTACHMENT_BYTES``.
MAX_ATTACHMENTS = 6
# What counts as a wall of text rather than a long question: past it, a
# block of the message is a document someone brought, kept apart.
PASTE_THRESHOLD = 2_000


def composer() -> dict[str, Any]:
    """What the chat composer takes, for its file input and its script:
    the server's limits, sent rather than copied. ``paste_threshold`` is
    None where a paste cannot be kept apart."""
    return {
        "types": sorted(ACCEPTED_TYPES),
        "images": sorted(IMAGE_TYPES),
        "kinds": "images or PDFs" if READS_PDF else "images",
        "max_bytes": MAX_ATTACHMENT_BYTES,
        "max_files": MAX_ATTACHMENTS,
        "paste_threshold": PASTE_THRESHOLD if _KEEPS_PASTES else None,
    }


class ChatAttachment(BaseModel):
    """One file of a chat turn, base64 over the JSON body: an image, or a
    PDF where one is read (``ACCEPTED_TYPES``)."""

    media_type: str
    # The byte cap as base64: four characters for every three bytes.
    data_b64: str = Field(max_length=-(-MAX_ATTACHMENT_BYTES // 3) * 4)
    name: str | None = None

    @field_validator("media_type")
    @classmethod
    def _taken(cls, media_type: str) -> str:
        if media_type not in ACCEPTED_TYPES:
            raise ValueError(f"{media_type} is not a file a chat turn takes")
        return media_type

    def decoded(self) -> bytes:
        try:
            return base64.b64decode(self.data_b64, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError(
                f"attachment {self.name or self.media_type!r} is not valid base64"
            ) from None


def build_user_content(
    context: str, attachments: list[ChatAttachment] | None
) -> str | list[Any]:
    """The user prompt for the model call: the conversation context,
    followed by each image as binary content. A document reached the turn
    as its text (``lift_turn``), so it is not shown. With no images the
    plain string goes through untouched - the zero-cost common case."""
    images, _ = _split(attachments)
    if not images:
        return context
    # Lazy: pydantic_ai is only installed when it is the chat framework.
    from pydantic_ai.messages import BinaryContent

    parts: list[Any] = [context]
    for attachment in images:
        parts.append(
            BinaryContent(data=attachment.decoded(), media_type=attachment.media_type)
        )
    return parts


def _split(
    attachments: list[ChatAttachment] | None,
) -> tuple[list[ChatAttachment], list[ChatAttachment]]:
    """A turn's files as (images, documents): the model is shown the
    first, and reads the second as text."""
    files = attachments or []
    return (
        [a for a in files if a.media_type in IMAGE_TYPES],
        [a for a in files if a.media_type not in IMAGE_TYPES],
    )


def annotate_attachments(
    message: str,
    attachments: list[ChatAttachment] | None,
    photos: list[dict[str, Any]] | None = None,
) -> str:
    """Stamp the stored user message with what was attached.

    History replays as text only, so this marker is how a later turn
    (or a text-only model) knows images rode this one. ``photos`` are the
    queued images' handles (``_read_later``): named in the marker,
    what a photo showed is a ``pasted`` call away in any later turn."""
    if not attachments:
        return message
    names = (
        ", ".join(
            f'{p["title"]} #{p["id"]}, what it showed: pasted("{p["id"]}")'
            for p in photos
        )
        if photos
        else ", ".join(a.name or a.media_type for a in attachments)
    )
    noun = "image" if len(attachments) == 1 else "images"
    return f"{message}\n\n[attached {len(attachments)} {noun}: {names}]"


async def persist_attachments(
    attachments: list[ChatAttachment] | None,
) -> list[dict[str, Any]]:
    """Keep the images, and describe where they went.

    The bytes ride one model call by design, but the picture itself is
    worth keeping: a reopened conversation should show the screenshot it
    is talking about, and a replay should not depend on session memory
    still holding megabytes. Each attachment is stored once - content
    addressing makes re-attaching the same image free - and the returned
    descriptors are what the message carries.

    Storage failing is not the user losing their turn: the question still
    goes to the model, the picture is simply not kept.
    """
    if not attachments:
        return []
    storage = get_storage()
    stored: list[dict[str, Any]] = []
    for attachment in attachments:
        # Decoded OUTSIDE the storage guard: a malformed payload is the
        # caller sending nonsense, not the store failing, and swallowing
        # it here would drop the image silently while logging a reason
        # that never happened.
        data = attachment.decoded()
        try:
            key = await storage.put(data, content_type=attachment.media_type)
        except OSError as exc:
            logger.warning(f"Could not store chat attachment: {exc}")
            continue
        stored.append(
            {
                "key": key,
                "media_type": attachment.media_type,
                "name": attachment.name,
            }
        )
    return stored


def attachment_metadata(stored: list[dict[str, Any]]) -> dict[str, Any]:
    """Message metadata for stored attachments, or nothing at all.

    A message that carried no image should read as one, so this returns
    an empty dict rather than a key holding an empty list.
    """
    return {"attachments": stored} if stored else {}


@dataclass(frozen=True)
class LiftedTurn:
    """A turn's text as it is kept (``lift_turn``): each attached document
    and wall of pasted text standing as its marker, the images that still
    ride as bytes, and the pastes the markers name, for the chips."""

    text: str
    images: list[ChatAttachment]
    pastes: list[dict[str, Any]] = field(default_factory=list)


def keeps_pastes(user_id: str) -> bool:
    """Whether ``user_id``'s turn has a paste index to be lifted into: none
    for no one, or where the AI service keeps no database."""
    return bool(user_id and _KEEPS_PASTES)


async def lift_turn(
    session: AsyncSession,
    message: str,
    attachments: list[ChatAttachment] | None,
    user_id: str,
    owner_user_id: int | None = None,
) -> LiftedTurn:
    """The turn as it is kept, lifted in ``session`` before it runs: an
    attached document is read and stands as its marker (``owner_user_id``
    owns it in the documents service), and a wall of pasted text is lifted
    to the store the same way. Only the images ride on as bytes. For a
    turn someone keeps (``keeps_pastes``)."""
    images, documents = _split(attachments)
    text, read = await _read_documents(session, message, documents, owner_user_id)
    text, pastes = await lift_pastes(session, text, user_id, read)
    return LiftedTurn(text, images, pastes)


async def prepare_turn(
    message: str,
    attachments: list[ChatAttachment] | None,
    user_id: str = "",
    lifted: LiftedTurn | None = None,
) -> tuple[str, dict[str, Any]]:
    """The stored message text and metadata for one turn.

    Both chat paths - streaming and not - need the same steps in the
    same order, and doing them by hand in each is how one of them ends
    up missing a step. One call, both callers, and every surface (the
    browser, the API, a CLI) gets them.

    ``lifted`` is the turn its way in lifted (``lift_turn``), standing for
    ``message`` and ``attachments``; without it the turn goes as it came,
    each document saying it went unread. No session here: the images are
    kept and queued, the text annotated.
    """
    turn = lifted
    if turn is None:  # nobody's to keep: each document says so
        images, documents = _split(attachments)
        no_reads = [None] * len(documents)
        turn = LiftedTurn(_with_documents(message, documents, no_reads), images)
    stored = await persist_attachments(turn.images)
    photos = await _read_later(user_id, stored)
    return annotate_attachments(turn.text, turn.images, photos), {
        **({"pastes": turn.pastes} if turn.pastes else {}),
        **attachment_metadata(stored),
    }


async def lift_pastes(
    session: AsyncSession, message: str, user_id: str, read: list[Any] | None = None
) -> tuple[str, list[dict[str, Any]]]:
    """``message`` with each wall of text in it kept apart and standing as
    its marker, and every paste its markers name (one the composer kept as
    it was pasted, too), for the chips under it; ``read`` are the turn's
    documents' lines, kept with them (``pastes.lift_walls``). Untouched
    where nothing can be kept, or for no one."""
    if not (user_id and _KEEPS_PASTES):
        return message, []
    from app.services.ai.domains.chat import pastes

    text, named = await pastes.lift_walls(session, user_id, message, read or [])
    return text, [p.model_dump() for p in named]


# Why a document produced no text, in the words the reader needs: a scan
# is answered with a screenshot, a reader that could not run by nobody.
UNREAD = {
    "unreadable": (
        "no text could be read from it - most likely a scan with no text "
        "layer. A screenshot of the part that matters will work"
    ),
    "broken": (
        "it could not be processed, which is not the same as it being "
        "unreadable - the text may be perfectly good. Say so rather than "
        "guessing at its contents"
    ),
}


async def _read_documents(
    session: AsyncSession,
    message: str,
    documents: list[ChatAttachment],
    owner_user_id: int | None,
) -> tuple[str, list[Any]]:
    """The message with each document's marker after it, or a line saying
    why it could not be read (``_with_documents``), and the lines read, for
    the index (``lift_pastes``). Read together, and waited on: the answer
    this turn waits on needs them (``pastes.read_documents``)."""
    if not documents:
        return message, []
    from app.services.ai.domains.chat import pastes

    found = await pastes.read_documents(session, documents, owner_user_id)
    read_lines = [p for p in found if isinstance(p, pastes.Paste)]
    return _with_documents(message, documents, found), read_lines


def _with_documents(
    message: str, documents: list[ChatAttachment], found: list[Any]
) -> str:
    """The message with each document's marker after it, or a line saying
    why it could not be read: an upload someone watched go and never hears
    of again reads as the app losing it. None found: nobody's to read."""
    if not documents:
        return message
    lines: list[str] = []
    for attachment, paste in zip(documents, found, strict=True):
        reason = "unreadable"
        if isinstance(paste, BaseException):  # a parser over uploaded bytes
            logger.warning(f"Could not read attached document: {paste}")
            paste, reason = None, "broken"
        name = attachment.name or "document"
        lines.append(paste.marker if paste else f"[{name}: {UNREAD[reason]}]")
    return "\n\n".join([message, *lines]).strip()


async def _read_later(
    user_id: str, stored: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Queue each kept photo to be indexed and read on the worker
    (``read_photo_job``); its handle, for the marker.

    The handle is the storage key's, so this turn touches no database for
    it, and a second vision call here would make every picture turn wait
    on two. Only where it can be read: a paste index (a database behind
    the AI service), a worker and the documents service's vision. Never
    fails the turn."""
    if not (stored and user_id and _READABLE):
        return []
    from app.components.worker import pools
    from app.core.constants import QueueName
    from app.services.ai.domains.chat.pastes import paste_id

    photos = []
    for s in stored:
        title = s.get("name") or "picture"
        try:
            await pools.enqueue_task(
                "read_photo_task",
                QueueName.SYSTEM,
                user_id,
                s["key"],
                s["media_type"],
                title,
            )
        except Exception as exc:  # noqa: BLE001 - the turn goes on regardless
            logger.warning(f"Could not queue a photo to be read: {exc}")
            continue
        photos.append({"id": paste_id(s["key"]), "title": title})
    return photos
