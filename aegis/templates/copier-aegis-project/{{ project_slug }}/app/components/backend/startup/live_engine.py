"""Seed the live engines at startup when missing.

Engines are table data; a missing row is added from the seeds, an edited
one is left alone. A missing table (migrations not yet run) must not stop
the app from booting.
"""

from typing import Any

from app.core.log import logger


async def startup_hook() -> Any:
    from app.core.db import get_async_session
    from app.services.ai.domains.voice import live_engines

    try:
        async with get_async_session() as session:
            added = await live_engines.seed_missing(session)
    except Exception:
        logger.exception("Could not seed the live engines")
        return None
    if added:
        logger.info("Live engines seeded: %d", added)
    return None
