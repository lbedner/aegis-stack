"""Research's tools (``app.core.tools.load_tools``): read what the owner's
watches found, for an agent or an MCP client. Read-only; adding a watch is
the user's, in the app."""

from app.core.db import get_async_session
from app.core.tools import current_owner_user_id, register_tool
from app.services.research.models import ResearchDay, ResearchHit
from app.services.research.service import ResearchService


async def research_search(
    text: str | None = None,
    source: str | None = None,
    kind: str | None = None,
    limit: int = 20,
) -> list[ResearchHit]:
    """Search what the user's research watches collected: outside posts
    and comments (Hacker News and other installed sources), newest first.
    ``text`` matches titles and bodies; ``source`` (e.g. "hn") and ``kind``
    (story, comment, post) narrow it. Each item has its score and comment
    count; read a whole discussion with ``research_thread``, and how an
    item's numbers moved day by day with ``research_history``."""
    async with get_async_session() as session:
        items = await ResearchService(session, current_owner_user_id.get()).search(
            text, source=source, kind=kind, limit=min(limit, 100)
        )
    return [ResearchHit.of(item) for item in items]


async def research_thread(item_id: int) -> list[ResearchHit]:
    """One discussion, top post first: the item ``item_id`` belongs to and
    every reply under it that was collected (a reply's ``parent_id`` is the
    item it answers). Empty if the user's watches never found it."""
    async with get_async_session() as session:
        items = await ResearchService(session, current_owner_user_id.get()).thread(
            item_id
        )
    return [ResearchHit.of(item) for item in items]


async def research_history(item_id: int) -> list[ResearchDay]:
    """An item's score and comment count a day at a time, oldest first:
    when a thread took off, and how far. Only days a watch refreshed it
    are there. Empty if the user's watches never found it."""
    async with get_async_session() as session:
        days = await ResearchService(session, current_owner_user_id.get()).history(
            item_id
        )
    return [ResearchDay.model_validate(day, from_attributes=True) for day in days]


register_tool("research_search", research_search, effect="read")
register_tool("research_thread", research_thread, effect="read")
register_tool("research_history", research_history, effect="read")
