"""The auth service's scheduled jobs (``app.core.schedule``)."""

from app.core.schedule import ServiceJob
from app.services.auth.jobs import cleanup_expired_refresh_tokens_job

JOBS: tuple[ServiceJob, ...] = (
    # Refresh tokens live for days or weeks and the table grows by at most
    # one row per device sign-in, so daily is plenty.
    ServiceJob(
        cleanup_expired_refresh_tokens_job,
        "auth_refresh_token_cleanup",
        "Auth: Refresh Token Cleanup",
        {"trigger": "interval", "hours": 24},
    ),
)
