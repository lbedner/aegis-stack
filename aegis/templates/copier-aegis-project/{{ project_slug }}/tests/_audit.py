"""The audit emitter for tests (``app.core.audit``): it keeps what it was
told, each event a dict with its ``event_type``."""

from typing import Any


class Recorded:
    """The audit emitter, keeping what it was told."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def emit(self, event_type: str, **fields: Any) -> None:
        self.events.append({"event_type": event_type, **fields})
