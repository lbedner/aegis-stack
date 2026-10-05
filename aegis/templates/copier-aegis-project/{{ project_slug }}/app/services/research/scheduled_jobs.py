"""Research's scheduled jobs (``app.core.schedule``)."""

from app.core.schedule import LONG_RUNNING, ServiceJob
from app.services.research.jobs import refresh_research_watches_job

JOBS: tuple[ServiceJob, ...] = (
    # Nightly: what a launch post or a discussion moved settles within a
    # day, and a source's search costs nothing to run once a night.
    ServiceJob(
        refresh_research_watches_job,
        "research_refresh",
        "Research: Refresh Watches",
        {"trigger": "cron", "hour": 3, "minute": 0},
        timeout=LONG_RUNNING,
    ),
)
