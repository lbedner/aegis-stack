"""The pastebox: staged OS-clipboard images, framework-level and generic.

A browser paste event cannot reach server-side UI code directly, so the
dashboard's capture script posts pasted images here and consumer
surfaces poll-drain them (chat attaches them to the next message; any
future surface can drain the same box and decide its own meaning).

Instance-wide and drain-once by design: the dashboard is a
single-operator surface, and whichever open consumer drains first owns
the paste. The box is bounded so an unattended browser cannot grow it.
"""

from __future__ import annotations

import base64
from collections import deque
from collections.abc import Callable
import time

# An incoming mark older than this is a failed/abandoned upload; the
# "receiving" indicator must not pin forever on it.
_INCOMING_TTL_SECONDS = 20.0


class Pastebox:
    """A bounded, drain-once store of pasted images.

    ``mark_incoming`` is the indicator half: the capture script pings it
    the instant a paste starts, before the (possibly slow) upload, so a
    consumer surface can show "receiving" during the gap. Staging
    consumes the oldest mark; stale marks expire on their own.
    """

    def __init__(
        self, max_items: int = 12, now: Callable[[], float] = time.monotonic
    ) -> None:
        self._items: deque[dict[str, str]] = deque(maxlen=max_items)
        self._incoming: deque[float] = deque()
        self._now = now

    def mark_incoming(self) -> None:
        self._incoming.append(self._now())

    def incoming(self) -> int:
        """Marks still awaiting their upload, stale ones dropped."""
        cutoff = self._now() - _INCOMING_TTL_SECONDS
        while self._incoming and self._incoming[0] < cutoff:
            self._incoming.popleft()
        return len(self._incoming)

    def stage(self, *, media_type: str, data: bytes, name: str | None) -> None:
        if self._incoming:
            self._incoming.popleft()
        self._items.append(
            {
                "media_type": media_type,
                "data_b64": base64.b64encode(data).decode(),
                "name": name or "pasted-image",
            }
        )

    def drain(self) -> list[dict[str, str]]:
        """Everything staged, oldest first, cleared in one move."""
        drained = list(self._items)
        self._items.clear()
        return drained


# The instance-wide box the capture endpoint stages into.
pastebox = Pastebox()
