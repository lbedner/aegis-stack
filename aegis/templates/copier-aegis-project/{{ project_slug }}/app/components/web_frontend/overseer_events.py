"""One health sampler per web process, fanned out over SSE to Overseer pages.

The initial page and every reconnect have a complete snapshot. Between those,
the sampler publishes only when a sidebar status changes. A bounded queue per
viewer holds the latest complete state, so a slow tab cannot grow memory.
"""

import asyncio
from collections.abc import AsyncIterator
import time
import weakref

from app.core.log import logger
from app.services.system.health import get_system_status, last_system_status

from .overseer_live import changed_frames
from .overseer_nav import build_navigation
from .overseer_server import overview_context
from .rendering import fragment

SAMPLE_INTERVAL_SECONDS = 30
HEARTBEAT_INTERVAL_SECONDS = 15
MAX_CONNECTION_SECONDS = 300


def _state() -> dict[str, str]:
    status = last_system_status()
    if status is None:
        return {}
    navigation = build_navigation(status)
    payloads = {
        entry.event: fragment(
            "pages/overseer/_status_dot.html", health_status=entry.status
        )
        for entries in navigation.values()
        for entry in entries
    }
    backend = next(
        (
            entry.component
            for entry in navigation["components"]
            if entry.name == "backend"
        ),
        None,
    )
    if backend is not None:
        payloads["server-overview"] = fragment(
            "pages/overseer/server/_overview.html",
            component=backend,
            **overview_context(backend),
        )
    return payloads


class _HealthFeed:
    def __init__(self) -> None:
        self.subscribers: set[asyncio.Queue[dict[str, str]]] = set()
        self.task: asyncio.Task[None] | None = None
        self.last_sent: dict[str, str] = {}

    def subscribe(self) -> asyncio.Queue[dict[str, str]]:
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue(maxsize=1)
        first_viewer = not self.subscribers
        self.subscribers.add(queue)
        snapshot = _state()
        if snapshot:
            queue.put_nowait(snapshot)
            if first_viewer:
                self.last_sent = snapshot
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._sample())
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, str]]) -> None:
        self.subscribers.discard(queue)
        if not self.subscribers and self.task is not None:
            self.task.cancel()
            self.task = None

    async def _sample(self) -> None:
        try:
            while self.subscribers:
                try:
                    await get_system_status()
                    snapshot = _state()
                    if snapshot != self.last_sent:
                        self.last_sent = snapshot
                        for queue in self.subscribers:
                            if queue.full():
                                queue.get_nowait()
                            queue.put_nowait(snapshot)
                except Exception as exc:
                    # Keep the last known status visible. The next interval
                    # retries without disconnecting every viewer.
                    logger.warning("Overseer health sample failed", error=str(exc))
                await asyncio.sleep(SAMPLE_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            pass


_feeds: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _HealthFeed] = (
    weakref.WeakKeyDictionary()
)


def _feed() -> _HealthFeed:
    loop = asyncio.get_running_loop()
    feed = _feeds.get(loop)
    if feed is None:
        feed = _HealthFeed()
        _feeds[loop] = feed
    return feed


async def health_events() -> AsyncIterator[str]:
    """Send a baseline and changed fragments using the htmx SSE format."""
    feed = _feed()
    queue = feed.subscribe()
    last_seen: dict[str, str] = {}
    deadline = time.monotonic() + MAX_CONNECTION_SECONDS
    try:
        while time.monotonic() < deadline:
            try:
                snapshot = await asyncio.wait_for(
                    queue.get(), timeout=HEARTBEAT_INTERVAL_SECONDS
                )
            except TimeoutError:
                yield ": heartbeat\n\n"
                continue
            for frame in changed_frames(last_seen, snapshot):
                yield frame
    finally:
        feed.unsubscribe(queue)
