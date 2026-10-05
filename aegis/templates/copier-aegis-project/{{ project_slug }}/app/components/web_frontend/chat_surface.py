"""The chat surface: what it renders from, wherever it is mounted.

The turn itself streams from ``POST /api/v1/ai/chat/stream`` straight to
the browser (static/js/chat.js); everything around it is server HTML. A
turn starts with the question and an empty bubble the script streams into
(``turn_context``) and settles as the stored message (``settled``), so a
history replay and a finished turn draw through the same macro and the
client never renders a settled message.

One surface, mounted as many times as an app needs (``ChatSurface``): the
Overseer's AI page and drawer are one mount; an app's own chat page, with
its own agent and its own user's conversations, is another. Every route
(``routes/partials/chat_surface.py``) and every helper here takes the
mount it serves.
"""

import importlib
import json
from dataclasses import dataclass
from importlib.util import find_spec
from typing import Any
from urllib.parse import urlencode

from app.components.backend.api.ai.service import ai_service
from app.core.chat_transcript import (
    card_markers,
    footer_line,
    strip_attachment_marker,
    trace_failed,
    trace_label,
    trace_output,
)
from app.core.log import logger
from fastapi import HTTPException

from .main import CHANGES

# What this stack has: voice (``ai[voice]``), and a database for the
# catalog, conversations and every row the surface reads.
PERSISTED = find_spec("app.services.ai.domains.chat.sentiment") is not None
HAS_VOICE = find_spec("app.services.ai.domains.voice") is not None
# The Overseer's helpers, where the Overseer ships (it serves logos).
OVERSEER_COMMON = "app.components.web_frontend.overseer_ai_common"

STREAM_URL = "/api/v1/ai/chat/stream"
HISTORY_LIMIT = 25
# A thread opens on its latest messages; earlier ones load a page at a time.
THREAD_PAGE = 40
# What a message of images alone says to the model.
IMAGES_ONLY = "See the attached images."
# The approval cards' routes. They ship with the change queue, which every
# persisted AI stack has, and the queue is all that leaves card markers.
CARDS: Any = importlib.import_module(CHANGES) if PERSISTED else None


@dataclass(frozen=True)
class ChatSurface:
    """One mount of the chat surface: the URL its routes live under, whose
    conversations it holds and the history they list under, and the agent
    that answers (None: the default agent)."""

    path: str
    user: str
    surface: str
    agent_slug: str | None = None
    # Who answers a live call: a voice agent (a quicker model, its own
    # prompt), else the chat agent.
    voice_agent_slug: str | None = None
    # A reply's drawer edits the agent behind it (the Overseer's agent
    # editor); a mount without one leaves the link out.
    agent_drawer: bool = False

    @property
    def turn_defaults(self) -> dict[str, Any]:
        """What every turn's stream request carries for this mount."""
        defaults = {"user_id": self.user, "surface": self.surface}
        if self.agent_slug:
            defaults["agent_slug"] = self.agent_slug
        return defaults


async def assistant_name(chat: ChatSurface, session: Any = None) -> str:
    """The answering agent's name, as the registry holds it. A route that
    holds a session passes it: a second one would wait on SQLite's write
    lock and fail ("database is locked")."""
    from app.services.ai.domains.chat.agent_loader import resolve_agent

    if chat.agent_slug:
        agent = await resolve_agent(chat.agent_slug, session=session)
    else:
        agent = await resolve_agent(session=session)
    return agent.name


async def conversations(chat: ChatSurface) -> list[Any]:
    """The mount's conversations, newest first."""
    return await ai_service.list_conversations(chat.user, surface=chat.surface)


async def find_conversation(chat: ChatSurface, conversation_id: str) -> Any | None:
    """The conversation, if it is the mount's user's: another user's is as
    absent as a missing one."""
    conversation = await ai_service.get_conversation(conversation_id)
    if conversation is None or conversation.metadata.get("user_id") != chat.user:
        return None
    return conversation


def find_message(conversation: Any, message_id: str) -> Any | None:
    return next((m for m in conversation.messages if m.id == message_id), None)


async def marks(names: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """``{key: logo URL}`` for the keys whose names the catalog holds a
    mark for, served by the Overseer's icon route; none on a stack without
    the Overseer, where there is no route to serve them."""
    if not PERSISTED or not names or find_spec(OVERSEER_COMMON) is None:
        return {}
    from app.core.db import get_async_session

    common = importlib.import_module(OVERSEER_COMMON)
    async with get_async_session() as db:
        return await common.mark_urls(db, names)


async def provider_icons(providers: list[str]) -> dict[str, str]:
    """``{provider: icon URL}`` for the providers that answered."""
    return await marks({p: (p,) for p in providers})


async def read_attachment(key: str) -> bytes | None:
    """A stored image's bytes by its content key, or None."""
    from app.core.storage import get_storage, validate_key

    try:
        validate_key(key)
    except ValueError:
        return None
    return await get_storage().get(key)


def spoken(text: str) -> str:
    """A message as it is said: its attachment note and the marks that only
    mean something on the page come off (``to_spoken``)."""
    from app.services.ai.domains.voice.spoken import to_spoken

    return to_spoken(strip_attachment_marker(text))


async def synthesize(text: str, tts: Any = None) -> bytes:
    """``text`` said aloud by the configured text-to-speech, or by ``tts``
    (a voice being previewed)."""
    from app.services.ai.domains.voice.models import SpeechRequest

    speaker = tts or ai_service.tts
    try:
        return (await speaker.synthesize(SpeechRequest(text=text))).audio
    except Exception:  # the provider's own: a key, the network, a format
        logger.exception("Speech synthesis failed")
        raise HTTPException(status_code=503, detail="Speech synthesis failed") from None


def _voice() -> dict[str, str]:
    """How a spoken turn is heard (static/js/voice.js): each sentence as it
    streams or the settled answer, and what plays while the assistant works
    in silence - the active voice profile's, applied onto the settings."""
    from app.core.config import settings

    return {
        "reply": settings.VOICE_REPLY,
        "sound": settings.VOICE_WORKING_SOUND,
        # A live call hangs up after this many seconds of dead air (0: never).
        "idle": settings.VOICE_LIVE_IDLE_SECONDS,
    }


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


def _message_url(chat: ChatSurface, conversation_id: str, message_id: str) -> str:
    return f"{chat.path}/messages/{conversation_id}/{message_id}"


def attachment_url(chat: ChatSurface, stored: dict[str, Any]) -> str:
    """Where a stored image is served from."""
    media_type = stored.get("media_type") or "image/png"
    return f"{chat.path}/attachments/{stored['key']}?" + urlencode({"type": media_type})


# What Continue sends after a reply the token limit cut off.
CONTINUE = "Continue exactly where you stopped."


def cut_off(meta: dict[str, Any]) -> str | None:
    """Why a reply ends mid-sentence, when the token limit is the reason."""
    if meta.get("finish_reason") != "length":
        return None
    # The agent's setting is the limit; a reply from before replies kept
    # it falls back to what it spent.
    configured = (meta.get("agent") or {}).get("max_tokens")
    tokens = int(configured or meta.get("output_tokens") or 0)
    limit = f"{tokens:,}-token" if tokens else "token"
    return f"Stopped at the {limit} limit."


def change_urls(trace: list[dict[str, Any]]) -> list[str]:
    """The approval cards a reply's tools proposed (``propose``,
    ``propose_many``) or listed (``pending``), once each, in order: the
    trace keeps each card's identity as its ``component`` marker."""
    if CARDS is None:
        return []
    markers = (card for entry in trace for card in card_markers(entry))
    return list(dict.fromkeys(u for m in markers if (u := CARDS.card_url(m))))


def drawn_card_urls(chat: ChatSurface, trace: list[dict[str, Any]]) -> list[str]:
    """The card a reply drew, at the mount's card route: one per answer, so
    a redraw (the first one fixed) replaces the card before it. Cards are
    rows, so none without a database."""
    if not PERSISTED:
        return []
    from app.services.ai.domains.chat.cards import MARKER

    drawn = [m for e in trace for m in card_markers(e) if m["kind"] == MARKER]
    return [f"{chat.path}/cards/{drawn[-1]['id']}"] if drawn else []


def settled(
    chat: ChatSurface,
    message: Any,
    conversation_id: str,
    icons: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One stored message, shaped for the bubble macro."""
    meta = message.metadata or {}
    url = _message_url(chat, conversation_id, message.id)
    return {
        "id": message.id,
        "role": message.role.value,
        "content": strip_attachment_marker(message.content),
        "attachments": [
            {"url": attachment_url(chat, a), "name": a.get("name") or "image"}
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
        "changes": change_urls(meta.get("tool_trace") or []),
        "cards": drawn_card_urls(chat, meta.get("tool_trace") or []),
        "footer": footer_line(meta),
        "cut_off": cut_off(meta),
        # The agent registry lives in the database: no drawer without it.
        "agent_url": f"{url}/agent" if PERSISTED and chat.agent_drawer else None,
        "turns_url": f"{chat.path}/turns",
        "continue_vals": {"message": CONTINUE, "conversation_id": conversation_id},
        "model_icon": (icons or {}).get(str(meta.get("provider") or "")),
        "speech": f"{url}/speech" if HAS_VOICE else None,
    }


def _providers(messages: list[Any]) -> list[str]:
    return sorted(
        {str(m.metadata["provider"]) for m in messages if m.metadata.get("provider")}
    )


async def transcript(
    chat: ChatSurface, conversation: Any | None, before: str | None = None
) -> dict[str, Any]:
    """A page of the thread: the latest messages, or those just before
    ``before``; ``earlier`` loads the page before it, when there is one."""
    assistant = await assistant_name(chat)
    if conversation is None:
        return {"assistant": assistant, "conversation_id": None, "messages": []}
    messages = conversation.messages
    if before:
        ids = [m.id for m in messages]
        messages = messages[: ids.index(before)] if before in ids else []
    page = messages[-THREAD_PAGE:]
    icons = await provider_icons(_providers(page))
    earlier = (
        f"{chat.path}/conversations/{conversation.id}/earlier?before={page[0].id}"
        if len(messages) > len(page)
        else None
    )
    return {
        "assistant": assistant,
        "conversation_id": conversation.id,
        "messages": [settled(chat, m, conversation.id, icons) for m in page],
        "earlier": earlier,
    }


async def message_context(
    chat: ChatSurface, conversation_id: str, message: Any
) -> dict[str, Any]:
    icons = await provider_icons(_providers([message]))
    return {
        "assistant": await assistant_name(chat),
        "message": settled(chat, message, conversation_id, icons),
    }


async def surface_context(chat: ChatSurface) -> dict[str, Any]:
    """The surface, wherever it is mounted: it opens on the most recent
    conversation, blank only when there is none."""
    latest = next(iter(await conversations(chat)), None)
    thread = await transcript(chat, latest)
    return thread | {
        "section_subtitle": f"Ask {thread['assistant']} anything",
        "chat_path": chat.path,
        "stream_url": STREAM_URL,
        "turn_defaults": chat.turn_defaults,
        "voice": _voice() if HAS_VOICE else None,
        "picker": PERSISTED,
        # Voice profiles are rows: the voice chip needs a database.
        "voices": HAS_VOICE and PERSISTED,
        # The change queue lives with a persisted AI backend.
        "approvals": CARDS.PATH if CARDS else None,
    }


async def turn_context(
    chat: ChatSurface, message: str, conversation_id: str, attachment_names: list[str]
) -> dict[str, Any] | None:
    """The question and the bubble its answer streams into, or None when
    there is nothing to send. The images ride the stream request from the
    browser; only their names come here, for the note under the bubble."""
    names = [n for n in attachment_names if n]
    text = message.strip() or (IMAGES_ONLY if names else "")
    if not text:
        return None
    return {
        "assistant": await assistant_name(chat),
        "text": text,
        "conversation_id": conversation_id or None,
        "attachment_names": names,
    }
