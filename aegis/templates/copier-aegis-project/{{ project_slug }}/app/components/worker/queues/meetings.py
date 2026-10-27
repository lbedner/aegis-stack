"""The meetings queue (arq): one job per call the bot is in, for as long
as the call lasts. A queue of its own, so an hour-long call never holds a
slot other jobs need; its concurrency is how many calls run at once."""

from typing import Any

from arq.connections import RedisSettings

from app.components.worker import arq_hooks
from app.core.config import settings
from app.core.constants import ServiceName
from app.core.ontology.system import warm
from app.core.queue_workers import concurrency_for
from app.services.meetings.service import run_meeting

# ponytail: arq always has a job timeout; a day stands in for none (the
# bot's own rules decide when it leaves).
A_DAY_SECONDS = 24 * 60 * 60

# What its jobs want ready as the worker starts (``queue_discovery.started``):
# her map (the twin) takes seconds to build, once a process.
STARTUP = (warm,)


async def run_meeting_task(ctx: dict[str, Any], meeting_id: int) -> None:
    """Take the bot through one meeting (``bot.run_meeting``)."""
    await run_meeting(meeting_id)


class WorkerSettings:
    """The meeting bot, one call per job."""

    description = "The meeting bot, one call per job"

    functions = [run_meeting_task]

    base_settings = RedisSettings.from_dsn(settings.redis_url_effective)
    redis_settings = RedisSettings(
        host=base_settings.host,
        port=base_settings.port,
        database=base_settings.database,
        password=base_settings.password,
        conn_timeout=settings.REDIS_CONN_TIMEOUT,
        conn_retries=settings.REDIS_CONN_RETRIES,
        conn_retry_delay=settings.REDIS_CONN_RETRY_DELAY,
    )
    queue_name = f"arq:queue:{ServiceName.MEETINGS}"
    max_jobs = concurrency_for(ServiceName.MEETINGS)  # Settings.WORKER_QUEUES
    job_timeout = A_DAY_SECONDS
    keep_result = settings.WORKER_KEEP_RESULT_SECONDS
    # A call is never run twice: one the worker lost is failed, not rejoined.
    max_tries = 1
    health_check_interval = settings.WORKER_HEALTH_CHECK_INTERVAL

    on_startup, on_shutdown, on_job_start, after_job_end = arq_hooks.for_queue(
        ServiceName.MEETINGS, max_jobs
    )
