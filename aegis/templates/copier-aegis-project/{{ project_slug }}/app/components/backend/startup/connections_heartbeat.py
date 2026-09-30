"""Keep this process's connection records alive (see
``middleware/connections.py``): a heartbeat the Server > Connections page
reads to tell a live connection from one a dead process left behind."""

import asyncio

from app.components.backend.middleware import connections

_task: asyncio.Task[None] | None = None


async def startup_hook() -> None:
    global _task
    _task = asyncio.create_task(connections.keep_alive())


def running() -> asyncio.Task[None] | None:
    return _task
