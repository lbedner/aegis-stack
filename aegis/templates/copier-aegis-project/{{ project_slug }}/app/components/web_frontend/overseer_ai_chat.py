"""The Overseer's chat: what the one chat surface renders from.

The turn itself streams from ``POST /api/v1/ai/chat/stream`` straight to
the browser (static/js/chat.js); everything around it is server HTML. A
turn starts with the question and an empty bubble the script streams into
(``turn_context``) and settles as the stored message (``settled``), so a
history replay and a finished turn draw through the same macro and the
client never renders a settled message. The surface shows as the AI
page's Chat section and in the drawer on every other Overseer page, one
instance at a time.
"""

import json
import re
from typing import Any
from urllib.parse import urlencode

from app.components.backend.api.ai.service import ai_service
from app.core.chat_transcript import (
    footer_line,
    strip_attachment_marker,
    trace_failed,
    trace_label,
    trace_output,
)

from .overseer_ai_common import HAS_VOICE, PARTIALS, PERSISTED, mark_urls
from .rendering import templates

PATH = f"{PARTIALS}/chat"
STREAM_URL = "/api/v1/ai/chat/stream"
# The chat API's own default user, and the surface its history lists under.
USER = "api-user"
SURFACE = "overseer"
TURN_DEFAULTS: dict[str, Any] = {"user_id": USER, "surface": SURFACE}
HISTORY_LIMIT = 25
# A thread opens on its latest messages; earlier ones load a page at a time.
THREAD_PAGE = 40
# What a message of images alone says to the model.
IMAGES_ONLY = "See the attached images."
# How a spoken turn is heard (static/js/voice.js): each sentence as it
# streams, and soft key taps while the assistant works in silence.
VOICE = {"reply": "live", "sound": "typing"}
# The Overseer shell mounts the chat drawer wherever this is set.
templates.env.globals["chat_path"] = PATH


async def assistant_name() -> str:
    """The default agent's name, as the registry holds it."""
    from app.services.ai.domains.chat.agent_loader import resolve_agent

    return (await resolve_agent()).name


async def conversations() -> list[Any]:
    """The Overseer's conversations, newest first."""
    return await ai_service.list_conversations(USER, surface=SURFACE)


async def find_conversation(conversation_id: str) -> Any | None:
    """The conversation, if it is the Overseer user's: another user's is
    as absent as a missing one."""
    conversation = await ai_service.get_conversation(conversation_id)
    if conversation is None or conversation.metadata.get("user_id") != USER:
        return None
    return conversation


def find_message(conversation: Any, message_id: str) -> Any | None:
    return next((m for m in conversation.messages if m.id == message_id), None)


async def provider_icons(providers: list[str]) -> dict[str, str]:
    """``{provider: icon URL}`` for the providers that answered."""
    if not PERSISTED or not providers:
        return {}
    from app.core.db import get_async_session

    async with get_async_session() as db:
        return await mark_urls(db, {p: (p,) for p in providers})


async def read_attachment(key: str) -> bytes | None:
    """A stored image's bytes by its content key, or None."""
    from app.core.storage import get_storage, validate_key

    try:
        validate_key(key)
    except ValueError:
        return None
    return await get_storage().get(key)


def spoken(text: str) -> str:
    """Markdown as it is said: the marks that only mean something on the
    page come off."""
    return re.sub(r"[*_`#>]+", "", strip_attachment_marker(text)).strip()


async def synthesize(text: str) -> bytes:
    """``text`` said aloud by the configured text-to-speech."""
    from app.services.ai.domains.voice.models import SpeechRequest

    return (await ai_service.tts.synthesize(SpeechRequest(text=text))).audio


def _pretty_json(value: Any) -> str | None:
    """Arguments as the reader wants them: re-indented when they parse."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return json.dumps(json.loads(value), indent=2, ensure_ascii=False)
    except ValueError:
        return value


def run(entry: dict[str, Any]) -> dict[str, Any]:
    """One tool run for its dialog: the script or arguments, the output."""
    code = entry.get("code") if isinstance(entry.get("code"), str) else None
    return {
        "tool": str(entry.get("tool") or "tool call"),
        "failed": trace_failed(entry),
        "code": code,
        "args": None if code else _pretty_json(entry.get("args")),
        "output": trace_output(entry),
    }


def _message_url(conversation_id: str, message_id: str) -> str:
    return f"{PATH}/messages/{conversation_id}/{message_id}"


def attachment_url(stored: dict[str, Any]) -> str:
    """Where a stored image is served from."""
    media_type = stored.get("media_type") or "image/png"
    return f"{PATH}/attachments/{stored['key']}?" + urlencode({"type": media_type})


def settled(
    message: Any, conversation_id: str, icons: dict[str, str] | None = None
) -> dict[str, Any]:
    """One stored message, shaped for the bubble macro."""
    meta = message.metadata or {}
    url = _message_url(conversation_id, message.id)
    return {
        "id": message.id,
        "role": message.role.value,
        "content": strip_attachment_marker(message.content),
        "attachments": [
            {"url": attachment_url(a), "name": a.get("name") or "image"}
            for a in meta.get("attachments") or []
            if a.get("key")
        ],
        "trail": [
            {
                "label": trace_label(e),
                "failed": trace_failed(e),
                "url": f"{url}/runs/{i}",
            }
            for i, e in enumerate(meta.get("tool_trace") or [])
        ],
        "footer": footer_line(meta),
        "model_icon": (icons or {}).get(str(meta.get("provider") or "")),
        "speech": f"{url}/speech" if HAS_VOICE else None,
    }


def _providers(messages: list[Any]) -> list[str]:
    return sorted(
        {str(m.metadata["provider"]) for m in messages if m.metadata.get("provider")}
    )


async def transcript(
    conversation: Any | None, before: str | None = None
) -> dict[str, Any]:
    """A page of the thread: the latest messages, or those just before
    ``before``; ``earlier`` loads the page before it, when there is one."""
    assistant = await assistant_name()
    if conversation is None:
        return {"assistant": assistant, "conversation_id": None, "messages": []}
    messages = conversation.messages
    if before:
        ids = [m.id for m in messages]
        messages = messages[: ids.index(before)] if before in ids else []
    page = messages[-THREAD_PAGE:]
    icons = await provider_icons(_providers(page))
    earlier = (
        f"{PATH}/conversations/{conversation.id}/earlier?before={page[0].id}"
        if len(messages) > len(page)
        else None
    )
    return {
        "assistant": assistant,
        "conversation_id": conversation.id,
        "messages": [settled(m, conversation.id, icons) for m in page],
        "earlier": earlier,
    }


async def message_context(conversation_id: str, message: Any) -> dict[str, Any]:
    icons = await provider_icons(_providers([message]))
    return {
        "assistant": await assistant_name(),
        "message": settled(message, conversation_id, icons),
    }


async def surface_context() -> dict[str, Any]:
    """The surface, for the section and the drawer alike: it opens on the
    most recent conversation, blank only when there is none."""
    latest = next(iter(await conversations()), None)
    thread = await transcript(latest)
    return thread | {
        "section_subtitle": f"Ask {thread['assistant']} anything",
        "chat_path": PATH,
        "stream_url": STREAM_URL,
        "turn_defaults": TURN_DEFAULTS,
        "voice": VOICE if HAS_VOICE else None,
        "picker": PERSISTED,
    }


async def turn_context(
    message: str, conversation_id: str, attachment_names: list[str]
) -> dict[str, Any] | None:
    """The question and the bubble its answer streams into, or None when
    there is nothing to send. The images ride the stream request from the
    browser; only their names come here, for the note under the bubble."""
    names = [n for n in attachment_names if n]
    text = message.strip() or (IMAGES_ONLY if names else "")
    if not text:
        return None
    return {
        "assistant": await assistant_name(),
        "text": text,
        "conversation_id": conversation_id or None,
        "attachment_names": names,
    }
