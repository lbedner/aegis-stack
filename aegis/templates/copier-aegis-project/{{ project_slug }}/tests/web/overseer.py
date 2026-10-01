"""Shared setup for the Overseer page tests: a signed-in viewer and a
health snapshot holding exactly the components a test hands in."""

from datetime import UTC, datetime

from fastapi import FastAPI
import pytest

from app.components.web_frontend import overseer_nav
from app.components.web_frontend.routes import pages
from app.core.config import settings
from app.models.user import User
from app.services.auth.deps import get_optional_user
from app.services.system.models import ComponentStatus, SystemStatus


def status_with(
    *components: ComponentStatus,
    services: tuple[ComponentStatus, ...] | list[ComponentStatus] = (),
) -> SystemStatus:
    """A snapshot with ``components`` and ``services`` in the dashboard's groups."""

    def group(
        name: str, members: tuple[ComponentStatus, ...] | list[ComponentStatus]
    ) -> ComponentStatus:
        return ComponentStatus(
            name=name, message="", sub_components={c.name: c for c in members}
        )

    aegis = ComponentStatus(
        name="aegis",
        message="",
        sub_components={
            "components": group("components", components),
            "services": group("services", services),
        },
    )
    return SystemStatus(
        components={"aegis": aegis}, overall_healthy=True, timestamp=datetime.now(UTC)
    )


def sign_in(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    status: SystemStatus,
    *,
    admin: bool = True,
) -> User:
    """Serve Overseer pages to a signed-in user from ``status``: an admin
    (on the allowlist, and the admin role under RBAC) unless ``admin`` is
    False, which signs in an ordinary member the Overseer refuses."""
    user = User(id=1, email="ops@example.com", hashed_password="x", is_active=True)
    if "role" in User.model_fields:  # RBAC: the viewer administers users
        user.role = "admin" if admin else "user"
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "ADMIN_USER_EMAILS", [user.email] if admin else [])
    app.dependency_overrides[get_optional_user] = lambda: user
    # Every Overseer route module that reads the snapshot sees this one.
    for module in (pages, overseer_nav):
        monkeypatch.setattr(module, "last_system_status", lambda: status)
    return user
