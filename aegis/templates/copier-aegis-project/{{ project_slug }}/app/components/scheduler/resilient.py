"""An AsyncIOScheduler that survives a failed pass.

APScheduler 3.x retries ``get_due_jobs()`` but not the write-back after a
run: a failed ``update_job()`` (SQLite "database is locked") escapes
``wakeup()`` before the timer is re-armed, and the scheduler never wakes
again while the process stays up. Here a failed pass logs and retries after
``jobstore_retry_interval``. The job whose write-back failed runs again,
which the misfire policy already assumes is safe (jobs are idempotent).
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.log import logger


class ResilientScheduler(AsyncIOScheduler):
    def wakeup(self) -> None:
        self._stop_timer()
        try:
            wait_seconds = self._process_jobs()
        except Exception:
            logger.exception("Scheduler pass failed; retrying")
            wait_seconds = self.jobstore_retry_interval
        self._start_timer(wait_seconds)
