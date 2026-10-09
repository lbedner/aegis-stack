"""The audit emitter for tests (``app.core.audit``): it keeps what it was
told, each event a dict with its ``event_type``; and the admin an audited
endpoint's test acts as."""

from typing import Any

from fastapi.testclient import TestClient

from app.core.audit import get_audit
from app.services.shared.deps import Actor, get_admin_actor

ADMIN = Actor(7, "ops@example.com", "ops@example.com")


class Recorded:
    """The audit emitter, keeping what it was told."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def emit(self, event_type: str, **fields: Any) -> None:
        self.events.append({"event_type": event_type, **fields})


def recording(client: TestClient) -> Recorded:
    """``client``'s audit, kept: what it was told."""
    recorded = Recorded()
    client.app.dependency_overrides[get_audit] = lambda: recorded
    return recorded


def as_admin(client: TestClient) -> TestClient:
    """``client`` acting as ``ADMIN``."""
    client.app.dependency_overrides[get_admin_actor] = lambda: ADMIN
    return client
