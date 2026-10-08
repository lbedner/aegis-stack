"""
Shared Dramatiq broker initialization.

Dramatiq uses a single global broker. This module initializes a
``PausableRedisBroker`` once; queue modules import ``broker`` from here
to register actors.

The broker is configured with:
- Results middleware for retrieving task return values
- EventPublishMiddleware for publishing lifecycle events to Redis Streams
- A pause-aware consumer that gates ``__next__`` on the
  ``aegis:queue:paused`` Redis flag, so ``aegis deploy --rolling`` can
  drain workers cleanly before recreating them. (Key name is shared
  with the taskiq variant so the deploy script's drain logic is
  queue-library-agnostic.)
"""

import logging
import time

import dramatiq
from app.components.worker.heartbeat import PAUSE_KEY, PAUSE_POLL_SECONDS
from app.components.worker.middleware import EventPublishMiddleware
from app.core.config import settings
from app.services.system.redis_keys import KeyFamily
# ``_RedisConsumer`` is dramatiq's internal consumer; there is no public
# base class to subclass for pause support, so we extend it to gate
# ``__next__`` on the pause flag. The dramatiq pin is capped to < 2.0 so a
# major release can't silently change this private API out from under us.
from dramatiq.brokers.redis import RedisBroker, _RedisConsumer
from dramatiq.middleware import AsyncIO
from dramatiq.results import Results
from dramatiq.results.backends.redis import RedisBackend

# What the broker keeps in Redis, for the keyspace map (``redis_keys``).
# Everything dramatiq writes sits under its namespace.
REDIS_KEYS = (
    KeyFamily(
        "dramatiq:*",
        "list",
        "Job queues",
        "Each queue's messages, delayed and dead-lettered ones, and acks",
        "Dramatiq broker",
        columns=("Member", "Value"),
    ),
)



_logger = logging.getLogger(__name__)


class _PausableRedisConsumer(_RedisConsumer):
    """Dramatiq Redis consumer that blocks ``__next__`` while paused.

    Before each fetch from the queue, checks ``PAUSE_KEY`` on the
    broker's Redis client. If set, sleeps and re-checks until cleared.
    The sleep blocks the consumer thread, which is exactly what we
    want during a rolling deploy — paused workers don't dequeue, and
    the heartbeat key they normally SET around in-flight jobs naturally
    expires/clears, letting the deploy's drain loop proceed.
    """

    def _is_paused(self) -> bool:
        try:
            return bool(self.broker.client.get(PAUSE_KEY))
        except Exception as exc:
            _logger.debug("pause flag check failed: %s", exc)
            return False

    def __next__(self):
        while self._is_paused():
            time.sleep(PAUSE_POLL_SECONDS)
        return super().__next__()


class PausableRedisBroker(RedisBroker):
    """``RedisBroker`` variant whose consumer respects ``PAUSE_KEY``."""

    @property
    def consumer_class(self):
        return _PausableRedisConsumer


# Use redis_url_effective for Docker vs local auto-detection
redis_url = settings.redis_url_effective

# Result backend for storing task return values
result_backend = RedisBackend(url=redis_url)

# Create a single global PausableRedisBroker
broker = PausableRedisBroker(url=redis_url)
broker.add_middleware(AsyncIO())
broker.add_middleware(Results(backend=result_backend))
broker.add_middleware(EventPublishMiddleware())

# Set as the global broker so @dramatiq.actor uses it
dramatiq.set_broker(broker)
