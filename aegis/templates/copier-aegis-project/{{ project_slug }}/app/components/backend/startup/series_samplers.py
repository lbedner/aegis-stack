"""Start sampling what Overseer's live charts draw (``app.core.series``,
``services/system/samplers.py``)."""

from app.components.backend import background
from app.core import series
from app.services.system.samplers import SAMPLERS

NAME = "series_samplers"


async def startup_hook() -> None:
    background.start(NAME, series.run(SAMPLERS))
