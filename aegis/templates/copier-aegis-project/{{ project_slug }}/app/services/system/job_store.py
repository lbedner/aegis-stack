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

import json
from typing import Any

from app.services.system.jobs import JobSnapshot, now_iso

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
        )

    async def aclose(self) -> None:
        await self._redis.aclose()
