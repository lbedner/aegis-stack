"""
Pause-aware TaskIQ broker for rolling deploys.

Wraps ``RedisStreamBroker`` so the consume loop gates on a Redis flag
(``aegis:queue:paused``) before pulling each batch from the stream. During a
rolling deploy (``aegis deploy --rolling``), the deploy script SETs the
flag, waits for in-flight jobs to drain via the per-worker heartbeat
key, then restarts worker containers. Workers that finish their current
job during the pause sit idle on the gate instead of consuming a new
message that would be killed by SIGTERM.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as aioredis
from taskiq import AckableMessage
from taskiq_redis import RedisStreamBroker
from taskiq_redis.redis_broker import logger as _broker_logger

from app.core.config import settings
from app.services.system.redis_keys import KeyFamily

PAUSE_KEY = "aegis:queue:paused"
PAUSE_POLL_SECONDS = 1.0

REDIS_KEYS = (
    KeyFamily(
        "taskiq:*",
        "stream",
        "Job queues",
        "One stream per queue: jobs waiting, and ones taken but not yet acked",
        "TaskIQ broker",
        columns=("Message", "Payload"),
    ),
    KeyFamily(
        "[0-9a-f]" * 32,
        "string",
        "Job results",
        "A finished job's return value under its bare task id, kept 60s",
        "TaskIQ result backend",
        columns=("Task", "Result"),
    ),
    KeyFamily(
        PAUSE_KEY,
        "string",
        "Queue pause",
        "Set during a rolling deploy so workers stop taking new jobs",
        "TaskIQ broker",
        columns=("Key", "Value"),
    ),
    KeyFamily(
        "autoclaim:*",
        "string",
        "Autoclaim locks",
        "Held while a worker reclaims jobs another worker left unacked",
        "TaskIQ broker",
        columns=("Key", "Value"),
    ),
)


class PausableRedisStreamBroker(RedisStreamBroker):
    """``RedisStreamBroker`` that gates ``listen()`` on a pause flag.

    The gate is checked before every ``XREADGROUP`` and before the
    pending/autoclaim sweep, so a paused worker never pulls a new
    message from the stream. Already-executing jobs are unaffected
    (the deploy script's drain wait handles those via the heartbeat).
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Each delivered job's stream entry, by task id, and the refresh
        # holding the claim of each one running (``keep_claim``).
        # ponytail: an entry the receiver drops unrun (an unknown task) is
        # never released; rare, and bounded by the redelivery cap.
        self._claims: dict[str, tuple[Any, Any]] = {}
        self._keeping: dict[str, asyncio.Task[None]] = {}

    def keep_claim(self, task_id: str) -> None:
        """Hold a running job's claim. ``xautoclaim`` (``listen``) hands a
        job unacked past ``idle_timeout`` to another worker, for a worker
        that died; refreshing the claim every third of that (``XCLAIM ...
        JUSTID``, no delivery counted) keeps a job that is still running
        from being run twice."""
        if task_id in self._claims and task_id not in self._keeping:
            self._keeping[task_id] = asyncio.create_task(
                self._keep(*self._claims[task_id])
            )

    def release_claim(self, task_id: str) -> None:
        """The job finished: stop holding its claim."""
        self._claims.pop(task_id, None)
        if (keeping := self._keeping.pop(task_id, None)) is not None:
            keeping.cancel()

    async def _keep(self, stream: Any, msg_id: Any) -> None:
        async with aioredis.Redis(connection_pool=self.connection_pool) as conn:
            while True:
                await asyncio.sleep(self.idle_timeout / 3000)
                try:
                    await conn.xclaim(
                        stream,
                        self.consumer_group_name,
                        self.consumer_name,
                        min_idle_time=0,
                        message_ids=[msg_id],
                        justid=True,
                    )
                except aioredis.RedisError as exc:
                    _broker_logger.warning(
                        "Could not refresh the claim on %s: %s", msg_id, exc
                    )

    def _delivered(self, stream: Any, msg_id: Any, data: bytes) -> AckableMessage:
        """A message for the receiver, its stream entry remembered by task
        id so the job can hold its claim while it runs."""
        try:
            self._claims[self.formatter.loads(message=data).task_id] = (stream, msg_id)
        except Exception as exc:  # the receiver skips it too
            _broker_logger.debug("No task id in %s: %s", msg_id, exc)
        return AckableMessage(data=data, ack=self._ack_generator(msg_id))

    async def _is_paused(self, conn: aioredis.Redis) -> bool:
        try:
            return bool(await conn.get(PAUSE_KEY))
        except Exception as exc:
            _broker_logger.debug("pause flag check failed: %s", exc)
            return False

    async def _wait_while_paused(self, conn: aioredis.Redis) -> None:
        while await self._is_paused(conn):
            await asyncio.sleep(PAUSE_POLL_SECONDS)

    async def listen(self) -> AsyncGenerator[AckableMessage]:
        """Re-implementation of ``RedisStreamBroker.listen`` with a pause gate.

        Mirrors the upstream loop (see ``taskiq_redis.redis_broker``):
        ``xreadgroup`` for new messages, then ``xautoclaim`` for
        pending/unacknowledged ones. A pause-flag check sits at the top
        of each iteration so neither fetch happens while paused.
        """
        async with aioredis.Redis(connection_pool=self.connection_pool) as redis_conn:
            while True:
                await self._wait_while_paused(redis_conn)

                _broker_logger.debug("Starting fetching new messages")
                fetched = await redis_conn.xreadgroup(
                    self.consumer_group_name,
                    self.consumer_name,
                    {
                        self.queue_name: ">",
                        **self.additional_streams,  # type: ignore[dict-item]
                    },
                    block=self.block,
                    noack=False,
                    count=self.count,
                )
                for stream, msg_list in fetched:
                    for msg_id, msg in msg_list:
                        yield self._delivered(stream, msg_id, msg[b"data"])

                if await self._is_paused(redis_conn):
                    continue

                for stream in [self.queue_name, *self.additional_streams.keys()]:
                    lock = redis_conn.lock(
                        f"autoclaim:{self.consumer_group_name}:{stream}",
                    )
                    if await lock.locked():
                        continue
                    async with lock:
                        pending = await redis_conn.xautoclaim(
                            name=stream,
                            groupname=self.consumer_group_name,
                            consumername=self.consumer_name,
                            min_idle_time=self.idle_timeout,
                            count=self.unacknowledged_batch_size,
                        )
                        for msg_id, msg in pending[1]:
                            if await self._is_poison(redis_conn, stream, msg_id):
                                continue
                            yield self._delivered(stream, msg_id, msg[b"data"])

    async def _is_poison(
        self,
        conn: aioredis.Redis,
        stream: str,
        msg_id: bytes,
    ) -> bool:
        """Drop a message that has been redelivered past the configured cap.

        Poison-message guard. ``xautoclaim`` (above) reclaims any message
        left unacknowledged longer than ``idle_timeout`` and re-yields it
        with NO delivery limit, so a task that KILLS its worker every run
        (OOM / SIGKILL) — and therefore never acks and never raises a
        catchable error for ``SimpleRetryMiddleware`` — loops forever,
        re-billing any paid work each lap. ``xautoclaim`` has just
        incremented this message's delivery counter, so we read it back via
        ``XPENDING``; once it exceeds ``WORKER_MAX_REDELIVERIES`` we ACK
        (drop) the message to break the loop and return ``True`` so the
        caller skips it. ``0`` disables the guard.

        Best-effort: any Redis error here falls through to delivering the
        message (fail open) rather than silently dropping work.
        """
        cap = settings.WORKER_MAX_REDELIVERIES
        if cap <= 0:
            return False
        try:
            info = await conn.xpending_range(
                stream,
                self.consumer_group_name,
                min=msg_id,
                max=msg_id,
                count=1,
            )
            delivered = int(info[0]["times_delivered"]) if info else 0
        except Exception as exc:
            _broker_logger.debug("poison-check XPENDING failed for %s: %s", msg_id, exc)
            return False

        if delivered <= cap:
            return False

        _broker_logger.warning(
            "Dropping poison message %s on %s after %d deliveries "
            "(cap=%d) — ACKing to stop the redelivery loop. A task that "
            "repeatedly kills its worker (e.g. OOM) lands here.",
            msg_id,
            stream,
            delivered,
            cap,
        )
        try:
            await conn.xack(stream, self.consumer_group_name, msg_id)
        except Exception as exc:
            _broker_logger.warning("poison-drop ACK failed for %s: %s", msg_id, exc)
        return True
