"""Research's tools (``app.core.tools.load_tools``): read what the owner's
watches found, for an agent or an MCP client. Read-only; adding a watch is
the user's, in the app."""

from typing import Any

from app.core.db import get_async_session
from app.core.tools import current_owner_user_id, register_tool
from app.services.research.models import ResearchItem
from app.services.research.service import ResearchService

# What a reply carries per item: enough to cite and judge it.
_SNIPPET = 280


def _item(item: ResearchItem) -> dict[str, Any]:
    return item.model_dump(
        mode="json",
        include={
            "id",
            "source",
            "kind",
            "title",
            "url",
            "author",
            "published_at",
            "score",
            "comment_count",
            "parent_id",
        },
    ) | {
        "text": (item.text or "")[:_SNIPPET] or None,
        "deleted": item.deleted_at is not None,
    }


async def research_search(
    text: str | None = None,
    source: str | None = None,
    kind: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search what the user's research watches collected: outside posts
    and comments (Hacker News and other installed sources), newest first.
    ``text`` matches titles and bodies; ``source`` (e.g. "hn") and ``kind``
    (story, comment, post) narrow it. Each item has its score and comment
    count; read a whole discussion with ``research_thread``."""
    async with get_async_session() as session:
        items = await ResearchService(session, current_owner_user_id.get()).search(
            text, source=source, kind=kind, limit=min(limit, 100)
        )
    return [_item(item) for item in items]


async def research_thread(item_id: int) -> list[dict[str, Any]]:
    """One discussion, top post first: the item ``item_id`` belongs to and
    every reply under it that was collected (a reply's ``parent_id`` is the
    item it answers). Empty if the user's watches never found it."""
    async with get_async_session() as session:
        items = await ResearchService(session, current_owner_user_id.get()).thread(
            item_id
        )
    return [_item(item) for item in items]


register_tool("research_search", research_search, effect="read")
register_tool("research_thread", research_thread, effect="read")
