"""Watching jobs this process is not running.

With a worker in the stack, the work happens elsewhere and writes its
progress to a shared store. The web server still has to answer for those
jobs - list them, stream them, say when they land - and it does that by
polling the store and feeding the same subscriber queues a local job
would have fed.

That is the whole job of this module: turn a store that must be asked
into changes that arrive. The runner owns local jobs and delegates
everything remote here, so neither half has to carry the other's
concerns.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.log import logger

from .jobs import JobSnapshot

DEFAULT_POLL_SECONDS = 0.5


class RemoteJobs:
    """A shared job store, polled on behalf of whoever is watching."""

    def __init__(self, store: Any, *, poll_seconds: float = DEFAULT_POLL_SECONDS) -> None:
        self._store = store
        self._poll_seconds = poll_seconds
        # One relay task per watched queue, so a watcher going away can
        # take its polling with it.
        self._relays: dict[int, asyncio.Task[None]] = {}
        self._all_task: asyncio.Task[None] | None = None

    async def get(self, job_id: str) -> JobSnapshot | None:
        """One job, or None when it is unknown or the store is unreachable."""
        try:
            return await self._store.get(job_id)
        except Exception as e:  # noqa: BLE001 - "not found" is the honest answer
            logger.warning(f"Job store unreachable: {e}")
            return None

    async def list_jobs(self) -> list[JobSnapshot]:
        """Every job in the store, or none when it is down.

        A Redis outage must not take the jobs list with it: the local jobs
        are still worth showing.
        """
        try:
            return list(await self._store.list_jobs())
        except Exception as e:  # noqa: BLE001 - degrade to local jobs, say so once
            logger.warning(f"Job store unreachable: {e}")
            return []

    def follow(
        self,
        job_id: str,
        queue: asyncio.Queue[dict[str, Any] | None],
        first: dict[str, Any],
    ) -> None:
        """Poll ``job_id`` into ``queue`` until it lands."""
        self._relays[id(queue)] = asyncio.create_task(
            self._relay(job_id, queue, first)
        )

    def stop_following(self, queue: asyncio.Queue[dict[str, Any] | None]) -> None:
        """The watcher is gone; polling for it is work for nobody."""
        relay = self._relays.pop(id(queue), None)
        if relay is not None:
            relay.cancel()

    def follow_all(
        self,
        subscribers: list[asyncio.Queue[dict[str, Any]]],
        is_local: Any,
    ) -> None:
        """Poll every job into ``subscribers`` while any of them remain."""
        if self._all_task is None or self._all_task.done():
            self._all_task = asyncio.create_task(
                self._relay_all(subscribers, is_local)
            )

    async def _relay(
        self,
        job_id: str,
        queue: asyncio.Queue[dict[str, Any] | None],
        last: dict[str, Any],
    ) -> None:
        """Forward changes to one job, then the terminal sentinel."""
        while True:
            await asyncio.sleep(self._poll_seconds)
            try:
                snapshot = await self._store.get(job_id)
            except Exception as e:  # noqa: BLE001 - end the stream, don't hang it
                # A watcher blocked on this queue has no other way to learn
                # the store went away: without the sentinel it waits forever.
                logger.warning(f"Job store unreachable while watching {job_id}: {e}")
                queue.put_nowait(None)
                return
            if snapshot is None:
                queue.put_nowait(None)
                return
            current = snapshot.as_dict()
            if current != last:
                queue.put_nowait(current)
                last = current
            if snapshot.status != "running":
                queue.put_nowait(None)
                return

    async def _relay_all(
        self,
        subscribers: list[asyncio.Queue[dict[str, Any]]],
        is_local: Any,
    ) -> None:
        """Forward every remote job's changes while anyone is watching.

        Local jobs publish themselves, so they are skipped here rather than
        arriving twice.
        """
        last: dict[str, dict[str, Any]] = {}
        while subscribers:
            for snapshot in await self.list_jobs():
                if is_local(snapshot.job_id):
                    continue
                current = snapshot.as_dict()
                if last.get(snapshot.job_id) != current:
                    last[snapshot.job_id] = current
                    for queue in subscribers:
                        queue.put_nowait(current)
            await asyncio.sleep(self._poll_seconds)
