"""The Overseer's mount of the chat surface (``chat_surface``): the AI
page's Chat section and the drawer on every other Overseer page, one
instance at a time, answering as the default agent for the API's own user.
"""

from typing import Any

from .chat_surface import ChatSurface
from .overseer_ai_common import PARTIALS
from .rendering import templates

OVERSEER = ChatSurface(
    path=f"{PARTIALS}/chat",
    # The chat API's own default user, and the history it lists under.
    user="api-user",
    surface="overseer",
    agent_drawer=True,
)
# The Overseer shell mounts the chat drawer wherever this is set.
templates.env.globals["chat_path"] = OVERSEER.path


def reply_used(meta: dict[str, Any]) -> list[tuple[str, Any]]:
    """The settings a reply ran under, from what its message kept."""
    agent = meta.get("agent") or {}
    tokens = agent.get("max_tokens")
    return [
        ("Model", meta.get("model")),
        ("Temperature", agent.get("temperature")),
        ("Max tokens", f"{tokens:,}" if isinstance(tokens, int) else None),
    ]


async def reply_agent_context(
    db: Any, message: Any, focus: str | None
) -> dict[str, Any] | None:
    """The agent behind a reply, in its drawer: what the reply used above
    the live editor, saved without leaving the chat."""
    from app.services.ai.domains.chat.agent_loader import DEFAULT_AGENT_SLUG

    from .overseer_ai_agents import agent_context

    meta = message.metadata or {}
    slug = (meta.get("agent") or {}).get("slug") or DEFAULT_AGENT_SLUG
    context = await agent_context(db, slug)
    if context is None:
        return None
    return context | {"used": reply_used(meta), "stay": True, "focus": focus}
