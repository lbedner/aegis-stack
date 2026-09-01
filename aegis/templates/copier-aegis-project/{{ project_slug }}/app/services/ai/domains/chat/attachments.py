"""Chat image attachments: generic multimodal message parts.

One module owns the whole shape so every surface stays in step: the
wire model (``ChatAttachment``, what the API accepts), the model-call
content (``build_user_content``, what the agent actually sees) and the
history marker (``annotate_attachments``, what later turns know). Any
agent on any chat surface gets attachments by threading this module -
nothing here belongs to a particular service or screen.

The bytes ride the current turn only: history replays as text, so the
marker records that a screenshot was there without re-sending it every
turn. Whether the model can SEE the image is the model's own capability
(a vision-capable pick like a Qwen-VL class model); a text-only model
still receives the marker and can say so.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

from pydantic import BaseModel

from app.core.log import logger
from app.core.storage import get_storage


class ChatAttachment(BaseModel):
    """One image part of a chat turn, base64 over the JSON body."""

    media_type: str
    data_b64: str
    name: str | None = None

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
    followed by each image as binary content. With no attachments the
    plain string goes through untouched - the zero-cost common case."""
    if not attachments:
        return context
    # Lazy: pydantic_ai is only installed when it is the chat framework.
    from pydantic_ai.messages import BinaryContent

    parts: list[Any] = [context]
    for attachment in attachments:
        parts.append(
            BinaryContent(data=attachment.decoded(), media_type=attachment.media_type)
        )
    return parts


def annotate_attachments(message: str, attachments: list[ChatAttachment] | None) -> str:
    """Stamp the stored user message with what was attached.

    History replays as text only, so this marker is how a later turn
    (or a text-only model) knows images rode this one."""
    if not attachments:
        return message
    names = ", ".join(a.name or a.media_type for a in attachments)
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


async def prepare_turn(
    message: str, attachments: list[ChatAttachment] | None
) -> tuple[str, dict[str, Any]]:
    """The stored message text and metadata for one turn's attachments.

    Both chat paths - streaming and not - need the same three steps in
    the same order, and doing them by hand in each is how one of them
    ends up missing a step. One call, both callers.
    """
    stored = await persist_attachments(attachments)
    return annotate_attachments(message, attachments), attachment_metadata(stored)
