"""Stop the connections heartbeat started at startup."""

from app.components.backend import background
from app.components.backend.startup import connections_heartbeat


async def shutdown_hook() -> None:
    await background.stop(connections_heartbeat.NAME)
