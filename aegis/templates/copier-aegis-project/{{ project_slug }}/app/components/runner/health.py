"""Health check for the runner (dashboard ComponentStatus): how many runs
wait and how many a runner has, across every owner, and whether a runner
is listening. A warning when a run waits and no runner that takes its
owner's is listening: nothing answers it."""

from enum import StrEnum

from app.core.constants import ComponentName
from app.core.db import get_async_session
from app.services.system.models import ComponentStatus, ComponentStatusType

from . import queries, tokens
from .models import ASKED, CLAIMED


class RunnerFact(StrEnum):
    """The keys this check publishes in ``metadata``; the card and modal
    read them back by these names."""

    WAITING = "waiting"
    RUNNING = "running"
    LISTENING = "listening"


async def check_runner_health() -> ComponentStatus:
    async with get_async_session() as db:
        standing = await queries.standing(db)
        waiting, running = standing.get(ASKED, 0), standing.get(CLAIMED, 0)
        unanswered = await tokens.unanswered(db) if waiting else 0
        listening = await tokens.listening(db, None)
    stuck = f", {unanswered} with no runner listening" if unanswered else ""
    return ComponentStatus(
        name=ComponentName.RUNNER,
        status=ComponentStatusType.WARNING if stuck else ComponentStatusType.HEALTHY,
        message=f"{waiting} waiting, {running} running{stuck}",
        metadata={
            RunnerFact.WAITING: waiting,
            RunnerFact.RUNNING: running,
            RunnerFact.LISTENING: listening,
        },
    )
