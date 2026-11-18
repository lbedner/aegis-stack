"""Stop the abandoned-runs sweep started at startup."""

from app.components.backend import background
from app.components.backend.startup import runner_recovery


async def shutdown_hook() -> None:
    await background.stop(runner_recovery.NAME)
