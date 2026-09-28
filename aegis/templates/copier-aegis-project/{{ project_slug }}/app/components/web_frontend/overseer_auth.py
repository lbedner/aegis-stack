"""Context for the Overseer Authentication page's sections and actions.

The Flet auth modal's Overview, Users and Sessions. Overview reads the auth
health metadata; Users and Sessions read through the same code as the API
routes. Actions are confirmations whose button calls the auth API itself,
as Flet does, so the API keeps its permissions, audit and cookie handling
(signing out "everywhere else" needs the refresh cookie, which only the
browser sends, and only to the API).
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.components.backend.api.auth.admin import (
    list_users,
    may_admin_users,
    may_read_users,
)
from app.components.backend.api.auth.sessions import session_responses
from app.core.formatting import format_relative_time
from app.models.refresh_token import SessionResponse
from app.models.user import User, UserResponse
from app.services.auth.refresh_tokens import RefreshService
from app.services.auth.users import UserService
from app.services.system import ui_auth
from app.services.system.models import ComponentStatus

from .filters import color_tone
from .overseer_nav import SectionRequest
from .rendering import status_cell

SECTIONS = (
    (None, {"overview": "Overview"}),
    ("Manage", {"users": "Users", "sessions": "Sessions"}),
)


# Where this page's dialogs and forms live (``routes/partials/overseer_auth``).
PARTIALS = "/partials/overseer/auth"


def _badge(label: str, color: str) -> dict[str, str]:
    return status_cell(label, color_tone(color))


# Both loaders take the request's own session. SQLite takes its write lock
# at BEGIN, so opening a second session while the request's is live waits
# out the busy timeout and fails with "database is locked".
async def load_users(db: AsyncSession) -> list[UserResponse]:
    return await list_users(user_service=UserService(db))


async def load_sessions(db: AsyncSession, viewer: User) -> list[SessionResponse]:
    """The viewer's sessions. Which one is this browser is unknown here: the
    refresh cookie is scoped to the auth API and never reaches Overseer."""
    rows = await RefreshService(db).list_sessions(viewer.id)
    return session_responses(rows, current_family=None)


def _overview(metadata: dict[str, Any]) -> dict[str, Any]:
    length = int(metadata.get("secret_key_length", 0) or 0)
    strength, strength_color = ui_auth.key_strength(length)
    level, description, level_color = ui_auth.security_level(metadata)
    configured = bool(metadata.get("secret_key_configured", False))
    return {
        "users": metadata.get("user_count_display", "0"),
        "algorithm": metadata.get("jwt_algorithm", "Unknown"),
        "expiry": metadata.get("token_expiry_display", "Unknown"),
        "key": "Configured" if configured else "Not configured",
        "strength": _badge(f"{strength} ({length} chars)", strength_color)
        if configured
        else None,
        "level": _badge(level.title(), level_color),
        "description": description,
        "issues": metadata.get("configuration_issues") or [],
    }


def _user_rows(users: list[UserResponse]) -> list[dict[str, Any]]:
    return [
        {
            "id": user.id,
            "active": user.is_active,
            "email": user.email,
            "name": user.full_name,
            "state": _badge("Active", "green")
            if user.is_active
            else _badge("Disabled", "yellow"),
            "verified": _badge("Verified", "green")
            if user.is_verified
            else _badge("Unverified", "yellow"),
            "created": format_relative_time(user.created_at.isoformat()),
            "last_login": format_relative_time(user.last_login.isoformat())
            if user.last_login
            else None,
        }
        for user in users
    ]


def _session_rows(sessions: list[SessionResponse]) -> list[dict[str, Any]]:
    rows = []
    for session in sessions:
        label, color = ui_auth.session_source(session.source)
        used = session.last_used_at or session.created_at
        rows.append(
            {
                "id": session.id,
                "source": _badge(label, color),
                "device": session.user_agent or "Unknown device",
                "ip": session.ip,
                "last_used": format_relative_time(used.isoformat()),
                "expires": session.expires_at,
            }
        )
    return rows


async def section_context(
    section: str, auth: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """What the named section's template needs beyond the auth status."""
    metadata = auth.metadata or {}
    available = bool(metadata.get("database_available", False))
    if section == "overview":
        return {"overview": _overview(metadata)}
    if section == "users":
        allowed = may_read_users(req.viewer)
        rows = _user_rows(await load_users(req.db)) if available and allowed else []
        return {
            "available": available,
            "allowed": allowed,
            "can_admin": may_admin_users(req.viewer),
            "users": rows,
            "partials": PARTIALS,
        }
    if section == "sessions":
        rows = (
            _session_rows(await load_sessions(req.db, req.viewer)) if available else []
        )
        return {"available": available, "sessions": rows, "partials": PARTIALS}
    return {}


def _user_confirmation(action: str, user: UserResponse) -> dict[str, str]:
    base = f"/api/v1/auth/users/{user.id}"
    if action == "delete":
        return {
            "title": "Delete user",
            "body": f"Delete {user.email}? They leave the user list and can no longer sign in.",
            "method": "delete",
            "url": base,
            "label": "Delete",
            "done": "User deleted",
        }
    enable = action == "activate"
    return {
        "title": "Enable user" if enable else "Disable user",
        "body": f"{'Enable' if enable else 'Disable'} {user.email}?"
        + ("" if enable else " They cannot sign in until enabled again."),
        "method": "patch",
        "url": f"{base}/{action}",
        "label": "Enable" if enable else "Disable",
        "done": "User enabled" if enable else "User disabled",
    }


def _session_confirmation(session: SessionResponse, delay: str) -> dict[str, str]:
    device = session.user_agent or "this device"
    return {
        "title": "Sign out this device",
        "body": f"Sign out {device}? It can take up to {delay} to take effect. "
        "If it is this browser, you will be signed out here too.",
        "method": "delete",
        "url": f"/api/v1/auth/sessions/{session.id}",
        "label": "Sign out",
        "done": "Device signed out",
    }


async def confirmation(
    action: str, target: str, auth: ComponentStatus, viewer: User, db: AsyncSession
) -> dict[str, str] | None:
    """The confirmation for one action, or None if it or its target is unknown."""
    delay = str((auth.metadata or {}).get("token_expiry_display", "a few minutes"))
    if action in ("activate", "deactivate", "delete"):
        user = next((u for u in await load_users(db) if str(u.id) == target), None)
        return _user_confirmation(action, user) if user else None
    if action == "revoke":
        sessions = await load_sessions(db, viewer)
        session = next((s for s in sessions if s.id == target), None)
        return _session_confirmation(session, delay) if session else None
    if action == "revoke-others" and target == "all":
        return {
            "title": "Sign out everywhere else",
            "body": f"Sign out all your other devices? Each can take up to {delay} to sign out.",
            "method": "delete",
            "url": "/api/v1/auth/sessions",
            "label": "Sign out others",
            "done": "Signed out other devices",
        }
    return None
