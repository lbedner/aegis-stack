"""A meeting whose run stopped (its process went down mid-call) is over:
say so (``fail_interrupted``), so none reads as still in a call.

It looks once a heartbeat's worth of time after startup: a run that died
with the last process has stopped beating by then, and a run another
process is in (``meetings join``) has not.
"""

import asyncio

from sqlalchemy.exc import SQLAlchemyError

from app.core.concurrency import background
from app.core.db import get_async_session
from app.core.log import logger
from app.services.meetings.service import STALE_SECONDS, fail_interrupted


async def _sweep_later() -> None:
    await asyncio.sleep(STALE_SECONDS)
    try:
        async with get_async_session() as session:
            count = await fail_interrupted(session)
    except SQLAlchemyError as e:
        # The table arrives with a migration that may not have run yet.
        logger.warning(f"Interrupted meetings not checked: {e}")
        return
    if count:
        logger.info(f"Marked {count} interrupted meeting(s) failed")


async def startup_hook() -> None:
    background(_sweep_later())
