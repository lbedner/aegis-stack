"""Start error collection independently of Overseer viewers."""

from app.components.backend import background
from app.components.backend.error_tracking.collector import run

NAME = "error_tracking"


async def startup_hook() -> None:
    background.start(NAME, run())
