"""The audit emitter for tests (``app.core.audit``): it keeps what it was
told, each event a dict with its ``event_type``; and the admin an audited
endpoint's test acts as."""

from importlib.util import find_spec
from typing import Any

from fastapi.testclient import TestClient
import pytest

from app.core.audit import get_audit
from app.services.shared.deps import Actor, get_admin_actor, get_admin_reader

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
    """``client`` acting as ``ADMIN``: its changes and its reads."""
    client.app.dependency_overrides[get_admin_actor] = lambda: ADMIN
    client.app.dependency_overrides[get_admin_reader] = lambda: None
    return client


def let_into_overseer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    """``client``'s user, let in the way Overseer lets an admin in, at any
    auth level: the admin role already does (``auth[org]``); basic auth has
    no roles, so its ``ADMIN_USER_EMAILS`` allowlist is given the user's
    email. Without auth Overseer is open: nothing to do."""
    if find_spec("app.models.user") is None:
        return client
    from app.core.config import settings
    from app.core.security import verify_token

    token = client.headers["Authorization"].removeprefix("Bearer ")
    claims = verify_token(token) or {}
    monkeypatch.setitem(settings.__dict__, "ADMIN_USER_EMAILS", [claims["sub"]])
    return client
