"""Stop the connections heartbeat started at startup."""

import asyncio
import contextlib

from app.components.backend.startup import connections_heartbeat


async def shutdown_hook() -> None:
    task = connections_heartbeat.running()
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
