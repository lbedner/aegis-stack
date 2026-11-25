"""Research's job: a sweep over the sources with watches, each source
refreshed on its own (``ServiceJob.each``), every owner's watches on it in
one pass."""

import logging

from app.core.db import get_async_session
from app.core.schedule import read_items
from app.services.research.service import refresh_source, watched_sources

logger = logging.getLogger(__name__)


async def refresh_research_watches_job() -> list[str]:
    """The sources some watch is on, each refreshed by
    ``refresh_research_watches_for``."""
    return await read_items(watched_sources)


async def refresh_research_watches_for(source: str) -> int:
    """One source's watches, every owner's: how many refreshed."""
    async with get_async_session() as session:
        found = await refresh_source(session, source)
    logger.info("Research: refreshed %d %s watches", len(found), source)
    return len(found)
