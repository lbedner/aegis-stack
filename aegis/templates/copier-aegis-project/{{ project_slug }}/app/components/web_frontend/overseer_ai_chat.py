"""The Overseer's mount of the chat surface (``chat_surface``): the AI
page's Chat section and the drawer on every other Overseer page, one
instance at a time, answering as the default agent. Each admin holds their
own conversations, the same ones the chat API lists for them (``own_user``).
"""

from dataclasses import replace
from typing import Any

from fastapi import Depends

from app.components.backend.api.ai.service import own_user

from .chat_surface import ChatSurface
from .overseer_access import Viewer, viewer
from .overseer_ai_common import HAS_EVALS, PARTIALS
from .rendering import templates


async def for_viewer(user: Viewer = Depends(viewer)) -> ChatSurface:
    """The mount as ``user`` holds it: their own conversations, under the
    id the chat API knows them by (``own_user``)."""
    return replace(OVERSEER, user=own_user(OVERSEER.user, user))


OVERSEER = ChatSurface(
    path=f"{PARTIALS}/chat",
    # Without sign-in, the chat API's one user; with it, bound per request.
    user="api-user",
    surface="overseer",
    agent_drawer=True,
    eval_cases=f"{PARTIALS}/evals/cases/new" if HAS_EVALS else None,
    bind=for_viewer,
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
    from app.services.ai.service import DEFAULT_AGENT_SLUG

    from .overseer_ai_agents import agent_context

    meta = message.metadata or {}
    slug = (meta.get("agent") or {}).get("slug") or DEFAULT_AGENT_SLUG
    context = await agent_context(db, slug)
    if context is None:
        return None
    return context | {"used": reply_used(meta), "stay": True, "focus": focus}
