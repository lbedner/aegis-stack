"""Cancel and await error collection, closing owned Redis connections."""

from app.components.backend import background
from app.components.backend.startup.error_tracking import NAME


async def shutdown_hook() -> None:
    await background.stop(NAME)
