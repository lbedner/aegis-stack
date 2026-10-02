"""Apply what the Overseer saved as the webserver starts (``app.core.boot``)."""

from app.core.boot import apply_saved_overrides


async def startup_hook() -> None:
    await apply_saved_overrides()
