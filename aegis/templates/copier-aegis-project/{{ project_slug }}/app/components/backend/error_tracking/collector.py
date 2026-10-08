"""One fenced collector per stack; Redis/Docker outages never block startup.

Input runs through bounded assembly and awaited writes: backpressure, not an
unbounded queue. A source's cursor is saved at most once a second, and replay
re-reads the second before it: ids dedupe the overlap.
"""

import asyncio
from datetime import UTC, datetime, timedelta
import json
import random
import time
from uuid import uuid4

from app.core import runtime
from app.core.config import settings
from app.core.runtime import Instance, RuntimeUnavailableError
from app.services.system.errors import scripts
from app.services.system.errors.client import repository, unavailable_reason
from app.services.system.errors.models import ErrorOccurrence
from app.services.system.errors.store import ErrorStore, StoreUnavailableError
from app.services.system.redis_keys import decoded

from .source import SourceReader

TICK = 5
LEASE_SECONDS = 20
CURSOR_SECONDS = 1.0  # the least time between two saves of a source's cursor


class LeaseLostError(RuntimeError):
    """Stop all pumps as soon as writes/renewals lose ownership."""


class Collector:
    def __init__(self, store: ErrorStore) -> None:
        self.store = store
        self.token = uuid4().hex
        self.pumps: dict[str, asyncio.Task[None]] = {}
        self.reasons: dict[str, str] = {}
        self.last_success: str | None = None
        self.dropped = 0

    async def status(self, state: str, reason: str = "") -> None:
        payload = json.dumps(
            {
                "state": state,
                "reason": reason,
                "last_success": self.last_success,
                "drops": self.dropped,
                "sources": len(self.pumps),
                "recovery": "Best effort within Docker log retention; restart identity and rotation completeness are unavailable.",
            }
        )
        await self.store.fenced(scripts.STATUS, self.token, "status", payload)

    async def commit(self, reader: SourceReader, events: list[ErrorOccurrence]) -> None:
        for event in events:
            result = await self.store.insert(event, token=self.token)
            if result == "fenced":
                raise LeaseLostError()
            self.dropped += result == "expired"
        at = reader.resume_at()
        now = time.monotonic()
        if (
            at is not None
            and at != reader.saved
            and now >= reader.saved_at + CURSOR_SECONDS
        ):
            if not await self.store.fenced(
                scripts.CURSOR,
                self.token,
                "cursors",
                reader.instance.id,
                at.isoformat(),
            ):
                raise LeaseLostError()
            reader.saved, reader.saved_at = at, now
        self.last_success = datetime.now(UTC).isoformat()

    async def source(self, instance: Instance, page: str) -> None:
        delay = 1.0
        while True:
            try:
                await self._connection(instance, page)
                self.reasons[instance.id] = (
                    "Log stream ended; reconnecting with overlap."
                )
                delay = 1.0  # it connected: backoff is for a source that keeps failing
            except (RuntimeUnavailableError, StoreUnavailableError) as exc:
                self.reasons[instance.id] = (
                    type(exc).__name__
                    + ": reconnecting; rotated input may be unavailable."
                )
            await asyncio.sleep(delay + random.random() * 0.25)
            delay = min(30.0, delay * 2)

    async def _connection(self, instance: Instance, page: str) -> None:
        saved = await self.store.call("hget", self.store.key("cursors"), instance.id)
        since = datetime.now(UTC) - timedelta(seconds=self.store.retention_seconds)
        if saved:
            since = max(
                since, datetime.fromisoformat(decoded(saved)) - timedelta(seconds=1)
            )
        reader = SourceReader(instance, page)
        stream = runtime.follow(instance.id, since=since)
        next_line = asyncio.create_task(anext(stream, None))
        try:
            while True:
                ready, _ = await asyncio.wait({next_line}, timeout=0.5)
                if not ready:
                    await self.commit(reader, reader.flush(now=time.monotonic()))
                    continue
                line = next_line.result()
                if line is None:
                    await self.commit(reader, reader.flush())
                    return
                await self.commit(reader, reader.feed(line, now=time.monotonic()))
                if reader.uncertain:
                    self.reasons[instance.id] = (
                        "Source timestamps missing; replay is uncertain."
                    )
                else:
                    self.reasons.pop(instance.id, None)
                next_line = asyncio.create_task(anext(stream, None))
        finally:
            next_line.cancel()
            await asyncio.gather(next_line, return_exceptions=True)
            await stream.aclose()

    async def discover(self) -> None:
        services = await runtime.services()
        sources = [
            (i, s.page)
            for s in services
            if s.page
            for i in s.instances
            if i.state == "running"
        ]
        limited = sources[: settings.ERROR_TRACKING_MAX_SOURCES]
        ids = {i.id for i, _ in limited}
        self.dropped += max(0, len(sources) - len(limited))
        removed = [key for key in self.pumps if key not in ids]
        for key in removed:
            task = self.pumps.pop(key)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.reasons.pop(key, None)
        cursors = await self.store.call("hkeys", self.store.key("cursors"))
        stale = [key for key in cursors if decoded(key) not in ids]
        if stale:
            await self.store.call("hdel", self.store.key("cursors"), *stale)
        for instance, page in limited:
            task = self.pumps.get(instance.id)
            if task is not None and task.done():
                task.result()  # lease loss must end every pump
            if task is None:
                self.pumps[instance.id] = asyncio.create_task(
                    self.source(instance, page)
                )
        await self.store.prune()
        reason = "; ".join(sorted(set(self.reasons.values())))
        if len(sources) > len(limited):
            reason += " Source limit exceeded."
        await self.status("degraded" if reason else "running", reason)

    async def owned(self) -> None:
        try:
            while await self.store.renew(self.token, LEASE_SECONDS):
                try:
                    await self.discover()
                except RuntimeUnavailableError:
                    await self.status(
                        "degraded", "Docker is unavailable; retrying discovery."
                    )
                await asyncio.sleep(TICK)
        finally:
            for task in self.pumps.values():
                task.cancel()
            await asyncio.gather(*self.pumps.values(), return_exceptions=True)
            self.pumps.clear()
            try:
                await self.store.renew(self.token, 0)
            except StoreUnavailableError:
                pass  # expiry releases the inaccessible lease

    async def run(self) -> None:
        while True:
            try:
                acquired = await self.store.call(
                    "set",
                    self.store.key("lease"),
                    self.token,
                    nx=True,
                    ex=LEASE_SECONDS,
                )
                if acquired:
                    await self.owned()
            except (StoreUnavailableError, LeaseLostError):
                # Status TTL makes stale health visible without logging into ourselves.
                pass
            await asyncio.sleep(TICK)


async def run() -> None:
    if unavailable_reason() is not None:
        return
    store = repository()
    try:
        await Collector(store).run()
    finally:
        await store.client.aclose()
