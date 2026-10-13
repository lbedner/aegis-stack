"""The meetings queue (Dramatiq): one job per call the bot is in, for as
long as the call lasts. A queue of its own, so an hour-long call never
holds a slot other jobs need; its concurrency is how many calls run at
once."""

# Import broker to ensure it is initialised before actors are registered
import app.components.worker.broker  # noqa: F401
import dramatiq
from app.core.constants import ServiceName
from app.services.meetings.bot import run_meeting

# ponytail: Dramatiq always has a time limit (ten minutes by default); a
# day stands in for none (the bot's own rules decide when it leaves).
A_DAY_MS = 24 * 60 * 60 * 1000


# A call is never run twice: one the worker lost is failed, not rejoined.
@dramatiq.actor(queue_name=ServiceName.MEETINGS, max_retries=0, time_limit=A_DAY_MS)
async def run_meeting_task(meeting_id: int) -> None:
    """Take the bot through one meeting (``bot.run_meeting``)."""
    await run_meeting(meeting_id)
