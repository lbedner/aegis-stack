"""Runs ``fail_interrupted`` every ``STALE_SECONDS``, first that long after
startup: a run that died with the last process, or a ``meetings join``
killed since, has stopped beating by then, and a live run has not."""

from app.components.backend import background
from app.core.db import get_async_session
from app.services.meetings.service import STALE_SECONDS, fail_interrupted

NAME = "meetings_recovery"


async def sweep_forever() -> None:
    await background.sweep_every(
        STALE_SECONDS, fail_interrupted, get_async_session, "interrupted meeting(s)"
    )


async def startup_hook() -> None:
    background.start(NAME, sweep_forever())
