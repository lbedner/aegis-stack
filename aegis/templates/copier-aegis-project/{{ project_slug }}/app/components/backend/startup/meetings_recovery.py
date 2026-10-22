"""Runs ``fail_interrupted`` every ``STALE_SECONDS``, first that long after
startup: a run that died with the last process, or a ``meetings join``
killed since, has stopped beating by then, and a live run has not. The
same sweep fails action runs a runner claimed and never finished."""

import asyncio

from sqlalchemy.exc import SQLAlchemyError

from app.components.backend import background
from app.core.db import get_async_session
from app.core.log import logger
from app.services.meetings.service import (
    STALE_SECONDS,
    fail_abandoned,
    fail_interrupted,
)

NAME = "meetings_recovery"


async def sweep_forever() -> None:
    while True:
        await asyncio.sleep(STALE_SECONDS)
        try:
            async with get_async_session() as session:
                count = await fail_interrupted(session)
                abandoned = await fail_abandoned(session)
        except SQLAlchemyError as e:
            # The table arrives with a migration that may not have run yet.
            logger.warning(f"Interrupted meetings not checked: {e}")
            continue
        if count:
            logger.info(f"Marked {count} interrupted meeting(s) failed")
        if abandoned:
            logger.info(f"Marked {abandoned} abandoned action run(s) failed")


async def startup_hook() -> None:
    background.start(NAME, sweep_forever())
