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
            BinaryContent(
                data=attachment.decoded(), media_type=attachment.media_type
            )
        )
    return parts


def annotate_attachments(
    message: str, attachments: list[ChatAttachment] | None
) -> str:
    """Stamp the stored user message with what was attached.

    History replays as text only, so this marker is how a later turn
    (or a text-only model) knows images rode this one."""
    if not attachments:
        return message
    names = ", ".join(a.name or a.media_type for a in attachments)
    noun = "image" if len(attachments) == 1 else "images"
    return f"{message}\n\n[attached {len(attachments)} {noun}: {names}]"
