"""Research's job: refresh every watch, every owner's, in one pass."""

import logging

from app.core.db import get_async_session
from app.services.research.refresh import refresh_every_watch

logger = logging.getLogger(__name__)


async def refresh_research_watches_job() -> None:
    async with get_async_session() as session:
        found = await refresh_every_watch(session)
    logger.info("Research: refreshed %d watches", len(found))
