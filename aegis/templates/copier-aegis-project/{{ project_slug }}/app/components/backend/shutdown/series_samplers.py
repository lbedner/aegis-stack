"""Stop the samplers started at startup."""

from app.components.backend import background
from app.components.backend.startup import series_samplers


async def shutdown_hook() -> None:
    await background.stop(series_samplers.NAME)
