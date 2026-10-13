"""The meetings queue (TaskIQ): one job per call the bot is in, for as long
as the call lasts. A queue of its own, so an hour-long call never holds a
slot other jobs need; its concurrency is how many calls run at once."""

from taskiq_redis import RedisAsyncResultBackend

from app.components.worker.broker import PausableRedisStreamBroker
from app.components.worker.middleware import EventPublishMiddleware
from app.core.config import settings
from app.core.constants import ServiceName
from app.services.meetings.bot import run_meeting

redis_url = settings.redis_url_effective

broker = (
    # ``consumer_id="0"``: a new group gets the backlog it was created to
    # work. One job per read: a call holds its slot for the whole call.
    PausableRedisStreamBroker(
        url=redis_url,
        queue_name=f"taskiq:{ServiceName.MEETINGS}",
        consumer_id="0",
        xread_count=1,
    )
    .with_result_backend(
        RedisAsyncResultBackend(redis_url=redis_url, result_ex_time=60)
    )
    .with_middlewares(EventPublishMiddleware().set_queue_name(ServiceName.MEETINGS))
)


@broker.task
async def run_meeting_task(meeting_id: int) -> None:
    """Take the bot through one meeting (``bot.run_meeting``). No timeout
    and no retry: a call delivered twice finds its meeting taken."""
    await run_meeting(meeting_id)
