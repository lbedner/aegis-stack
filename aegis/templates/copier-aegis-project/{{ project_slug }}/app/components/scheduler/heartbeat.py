"""Scheduler liveness heartbeat.

An interval job touches a beacon file; the container healthcheck compares
its mtime against a staleness window. The file path is duplicated in
docker-compose's scheduler healthcheck command.
"""

from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

HEARTBEAT_FILE = Path("/tmp/aegis-scheduler-heartbeat")
HEARTBEAT_JOB_ID = "scheduler_heartbeat"


async def touch_scheduler_heartbeat() -> None:
    """Liveness beacon proving the scheduler is actually firing jobs."""
    HEARTBEAT_FILE.touch()


def register_heartbeat_job(scheduler: AsyncIOScheduler) -> None:
    """Register the beacon job on the scheduler."""
    scheduler.add_job(
        touch_scheduler_heartbeat,
        trigger="interval",
        seconds=15,
        id=HEARTBEAT_JOB_ID,
        name="Scheduler Heartbeat",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )


def is_heartbeat_event(event: Any) -> bool:
    """True for job events the execution log should ignore: the heartbeat
    fires constantly and would flood activity and history."""
    return bool(getattr(event, "job_id", None) == HEARTBEAT_JOB_ID)
