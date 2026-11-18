"""Fails runs a runner claimed and never finished (``runs.fail_abandoned``),
every ``SWEEP_SECONDS``: its runner died with it, or a restart took the
app's own."""

from app.components.backend import background
from app.components.runner import runs
from app.core.db import get_async_session

NAME = "runner_recovery"
SWEEP_SECONDS = 60


async def sweep_forever() -> None:
    await background.sweep_every(
        SWEEP_SECONDS, runs.fail_abandoned, get_async_session, "abandoned run(s)"
    )


async def startup_hook() -> None:
    background.start(NAME, sweep_forever())
