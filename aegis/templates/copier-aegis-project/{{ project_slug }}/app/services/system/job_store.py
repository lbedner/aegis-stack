"""Job state that outlives the process that started it.

The in-process runner (``jobs.py``) keeps state in memory, which is right
when the webserver does the work itself. With a worker in the stack the
work happens in another process, so the record lives in Redis: the
webserver writes the job as queued, the worker narrates progress and the
result into the same hash, and the jobs API reads whichever it finds.

One hash per job, ``jobs:<id>``, with a TTL so finished jobs age out on
their own. No pub/sub: the runner polls the hash while a client is
subscribed, which is a read every half second and nothing to keep alive.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
from typing import Any
import uuid

from app.core.discovery import present
from app.services.system.jobs import (
    JobSnapshot,
    Report,
    SetLabel,
    get_job_runner,
    now_iso,
)

KEY_PREFIX = "jobs:"
# Long enough for a client that asks after the fact, short enough that a
# busy day of extractions does not accumulate.
KEEP_SECONDS = 6 * 3600


class RedisJobStore:
    """The remote half of the job API, over any redis.asyncio-shaped client."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    @classmethod
    def from_url(cls, url: str) -> RedisJobStore:
        import redis.asyncio as aioredis

        return cls(aioredis.from_url(url, decode_responses=True))

    @classmethod
    def shared(cls) -> RedisJobStore:
        """The store the webserver and the worker share, where this process
        reaches Redis (``redis_url_effective``: the compose hostname inside
        Docker, the published port on the host). Only a stack with a worker,
        hence Redis, asks for it."""
        from app.services.system.redis_keys import redis_url

        return cls.from_url(redis_url())

    @staticmethod
    def _key(job_id: str) -> str:
        return f"{KEY_PREFIX}{job_id}"

    async def _write(self, job_id: str, **fields: str) -> None:
        key = self._key(job_id)
        await self._redis.hset(key, mapping=fields)
        await self._redis.expire(key, KEEP_SECONDS)

    async def create(self, job_id: str, name: str, label: str) -> None:
        await self._write(
            job_id,
            name=name,
            status="running",
            label=label,
            result="",
            error="",
            started_at=now_iso(),
        )

    async def set_label(self, job_id: str, label: str) -> None:
        await self._write(job_id, label=label)

    async def set_run(self, job_id: str, run_id: str) -> None:
        """The worker task the job was handed to: the run whose log is
        the job's, since the worker binds its own task id."""
        await self._write(job_id, run=run_id)

    def label_writer(self, job_id: str) -> SetLabel:
        """One job's label as a ``SetLabel``, so work running on a worker
        narrates itself the same way in-process work does."""

        async def write(label: str) -> None:
            await self.set_label(job_id, label)

        return write

    async def finish(self, job_id: str, result: dict[str, Any] | None) -> None:
        await self._write(job_id, status="done", result=json.dumps(result or {}))

    async def fail(self, job_id: str, error: str) -> None:
        await self._write(job_id, status="failed", error=error)

    async def list_jobs(self) -> list[JobSnapshot]:
        """Every job still in the store (they expire on their own)."""
        snapshots: list[JobSnapshot] = []
        async for key in self._redis.scan_iter(match=f"{KEY_PREFIX}*"):
            name = key.decode() if isinstance(key, bytes) else key
            snapshot = await self.get(name[len(KEY_PREFIX) :])
            if snapshot is not None:
                snapshots.append(snapshot)
        return snapshots

    async def get(self, job_id: str) -> JobSnapshot | None:
        raw = await self._redis.hgetall(self._key(job_id))
        if not raw:
            return None
        fields = {
            (k.decode() if isinstance(k, bytes) else k): (
                v.decode() if isinstance(v, bytes) else v
            )
            for k, v in raw.items()
        }
        return JobSnapshot(
            job_id=job_id,
            name=fields.get("name", ""),
            status=fields.get("status", "running"),
            label=fields.get("label", ""),
            result=json.loads(fields["result"]) if fields.get("result") else None,
            error=fields.get("error") or None,
            started_at=fields.get("started_at", ""),
            run_id=fields.get("run", ""),
        )

    async def aclose(self) -> None:
        await self._redis.aclose()


async def start_job(
    name: str,
    task: str,
    args: tuple[Any, ...],
    work: Callable[[Report], Awaitable[dict[str, Any]]],
    *,
    label: str = "Queued...",
) -> str:
    """Start ``work`` as a job: handed to the worker as ``task`` (called
    with the job id and ``args``) where the stack has one, else run as an
    asyncio task here. The job id either way, followed the same way."""
    if present("app.components.worker"):
        return await queue_job(name, task, *args)
    return get_job_runner().start(
        name, lambda handle: work(handle.set_label), label=label
    )


async def queue_job(name: str, task: str, *args: Any) -> str:
    """Record ``name`` as queued, then hand ``task`` (called with the job id
    and ``args``) to the worker on the system queue. The job id."""
    job_id = uuid.uuid4().hex
    store = RedisJobStore.shared()
    try:
        await store.create(job_id, name, "Queued...")
        try:
            # The worker binds its task id as the run: the job's log is there.
            await store.set_run(job_id, await _enqueue(task, job_id, *args))
        except Exception as exc:
            # The record outlives this function, so a failed hand-off has to
            # be written into it: otherwise the job sits "Queued..." until it
            # expires, with the reason only in this process's logs.
            await store.fail(job_id, f"Could not queue the job: {exc}")
            raise
    finally:
        await store.aclose()
    return job_id


async def _enqueue(task: str, *args: Any) -> str:
    """Hand ``task`` to the worker; the task id it runs under."""
    from app.components.worker import pools
    from app.core.constants import QueueName

    # The one way work reaches the queue: its feed, its history, its edge.
    return pools.job_id(await pools.enqueue_task(task, QueueName.SYSTEM, *args))


async def narrate(
    job_id: str, work: Callable[[Report], Awaitable[dict[str, Any]]]
) -> dict[str, Any]:
    """The worker's side of a job: ``work`` reports into the shared record,
    which then holds its result or why it failed."""
    store = RedisJobStore.shared()
    loop = asyncio.get_running_loop()
    # Labels are written without waiting, so the work is never held up by
    # Redis - but they are held here, because closing the client out from
    # under a write in flight loses the progress it carried.
    writes: set[asyncio.Task[None]] = set()

    def report(label: str) -> None:
        task = loop.create_task(store.set_label(job_id, label))
        writes.add(task)
        task.add_done_callback(writes.discard)

    try:
        result = await work(report)
        await store.finish(job_id, result)
        return result
    except Exception as exc:
        await store.fail(job_id, str(exc) or type(exc).__name__)
        raise
    finally:
        if writes:
            await asyncio.gather(*writes, return_exceptions=True)
        await store.aclose()
