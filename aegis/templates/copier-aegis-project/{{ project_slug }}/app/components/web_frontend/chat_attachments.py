"""What a question carries besides its words, on any mount of the chat
surface: the images attached to it (stored by content key) and the walls of
text lifted out of it (``lift_pastes``), each served at the mount's route.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from app.core.chat_transcript import paste_size

if TYPE_CHECKING:
    from .chat_surface import ChatSurface


async def read_attachment(key: str) -> bytes | None:
    """A stored image's bytes by its content key, or None."""
    from app.core.storage import get_storage, validate_key

    try:
        validate_key(key)
    except ValueError:
        return None
    return await get_storage().get(key)


def attachment_url(chat: ChatSurface, stored: dict[str, Any]) -> str:
    """Where a stored image is served from."""
    media_type = stored.get("media_type") or "image/png"
    return f"{chat.path}/attachments/{stored['key']}?" + urlencode({"type": media_type})


def paste_chips(
    chat: ChatSurface, pastes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The pastes a question carries (``lift_pastes``), each as the chip
    that opens it whole at the mount's paste route."""
    return [
        {
            "id": p["id"],
            "title": p["title"],
            "size": paste_size(p.get("chars") or 0),
            "url": f"{chat.path}/pastes/{p['id']}",
        }
        for p in pastes
    ]
