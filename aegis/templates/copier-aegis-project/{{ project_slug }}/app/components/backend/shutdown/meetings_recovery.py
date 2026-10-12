"""Stop the interrupted-meetings sweep started at startup."""

from app.components.backend import background
from app.components.backend.startup import meetings_recovery


async def shutdown_hook() -> None:
    await background.stop(meetings_recovery.NAME)
