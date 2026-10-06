"""Context for the Overseer Authentication page's sections and actions.

The Flet auth modal's Overview, Users and Sessions. Overview reads the auth
health metadata; Users and Sessions read through the same code as the API
routes. Actions are confirmations whose button calls the auth API itself,
as Flet does, so the API keeps its permissions, audit and cookie handling.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.components.backend.api.auth.admin import (
    list_users,
    may_admin_users,
    may_read_users,
)
from app.core.config import settings
from app.core.formatting import (
    CLOCK,
    counted,
    format_relative_time,
    format_span,
    row_matches,
)
from app.core.security import access_token_minutes
from app.models.refresh_token import SessionEnd, SessionHistory
from app.models.user import User, UserResponse
from app.services.auth import session_history
from app.services.auth.users import UserService
from app.services.system import ui_auth
from app.services.system.models import ComponentStatus

from .filters import color_tone
from .overseer_nav import SectionRequest, page_url
from .rendering import page_number, pager, status_cell, with_query

SECTIONS = (
    (None, {"overview": "Overview"}),
    ("Manage", {"users": "Users", "sessions": "Sessions"}),
)


PAGE = page_url("services", "auth")
SESSIONS = f"{PAGE}/sessions"
# Where this page's dialogs and forms live (``routes/partials/overseer_auth``).
PARTIALS = "/partials/overseer/auth"
PAGE_SIZE = 50  # live sessions a page
ENDED_SHOWN = 50  # the latest ended sessions
# How an ended sign-in ended, as the Sessions page says it: the table
# records a revocation, not whether a sign-out or a caught replay made it.
ENDED = {SessionEnd.EXPIRED: "Expired", SessionEnd.REVOKED: "Signed out or revoked"}
RENEWALS_SHOWN = 5  # a session's latest renewals, in its details


def _badge(label: str, color: str) -> dict[str, str]:
    return status_cell(label, color_tone(color))


# Both loaders take the request's own session. SQLite takes its write lock
# at BEGIN, so opening a second session while the request's is live waits
# out the busy timeout and fails with "database is locked".
async def load_users(db: AsyncSession) -> list[UserResponse]:
    return await list_users(user_service=UserService(db))


async def load_history(db: AsyncSession, viewer: User) -> list[SessionHistory]:
    """The sign-ins the viewer may see, live and lately ended: every user's
    for whoever may read users (the app's administrators), else their own."""
    if may_read_users(viewer):
        return await session_history.everyone(db)
    return await session_history.history(db, viewer.id)


async def load_session(db: AsyncSession, family_id: str) -> SessionHistory | None:
    """One sign-in, by its id (``session_history.one``)."""
    return await session_history.one(db, family_id)


async def load_people(db: AsyncSession, ids: list[int]) -> dict[int, User]:
    """The users with these ids, in one query; a deleted one is absent."""
    return await UserService(db).get_users_by_ids(ids)


async def load_session_counts(db: AsyncSession) -> dict[int, int]:
    """Each user's live sessions (``session_history.live_counts``)."""
    return await session_history.live_counts(db)


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


def _user_rows(
    users: list[UserResponse], sessions: dict[int, int], viewer: User
) -> list[dict[str, Any]]:
    """Each account, with its live sessions (a link to them) and whether it
    can be signed out everywhere (never the viewer: theirs is "everywhere
    else", on Sessions)."""
    return [
        {
            "id": user.id,
            "active": user.is_active,
            "sessions": {"label": sessions[user.id], "url": _sessions_of(user.id)}
            if sessions.get(user.id)
            else None,
            "signed_in": bool(sessions.get(user.id)) and user.id != viewer.id,
            "email": user.email,
            "name": user.full_name,
            "state": _badge("Active", "green")
            if user.is_active
            else _badge("Disabled", "yellow"),
            "verified": _badge("Verified", "green")
            if user.is_verified
            else _badge("Unverified", "yellow"),
            "created": format_relative_time(user.created_at),
            "last_login": format_relative_time(user.last_login)
            if user.last_login
            else None,
        }
        for user in users
    ]


def _lifetimes(metadata: dict[str, Any]) -> str:
    """How long each token lasts: the session cookie (the auth health
    check's figure) renews from the refresh token when it runs out; longer
    in dev (``DEV_TOKEN_EXPIRE_MULTIPLIER``)."""
    minutes, base = access_token_minutes(), settings.ACCESS_TOKEN_EXPIRE_MINUTES
    dev = f" ({base} min × {minutes // base} in dev)" if minutes != base else ""
    cookie = metadata.get("token_expiry_display", f"{minutes} min")
    days = counted(settings.REFRESH_TOKEN_EXPIRE_DAYS, "day")
    return f"Session cookie {cookie}{dev} · Refresh token {days}"


def _session_rows(
    sessions: list[SessionHistory],
    viewer: User,
    people: dict[int, User],
    current: str | None,
    expires: datetime | None,
) -> list[dict[str, Any]]:
    """The live sign-ins, newest use first, each with its user; ``current``
    is this browser's, whose session cookie runs out at ``expires``. The
    viewer may sign out their own others, and anyone's if they administer
    users."""
    rows = []
    for session in sessions:
        label, color = ui_auth.session_source(session.source)
        here = session.id == current
        renewals = session.renewals
        rows.append(
            {
                "id": session.id,
                "current": here,
                "can_sign_out": _may_sign_out(session, viewer, current),
                "user": _who(people, session.user_id),
                "source": _badge(label, color),
                "device": _device(session),
                "signed_in": format_relative_time(session.signed_in),
                "renewed": _renewed(renewals),
                "last_used": format_relative_time(session.last_used_at),
                "expires": session.expires_at,
                "facts": [
                    ("Device", session.user_agent),
                    ("IP", session.ip),
                    ("This browser", _cookie(expires) if here else None),
                    *_renewal_facts(renewals),
                ],
            }
        )
    return rows


def _renewed(renewals: list[datetime]) -> str:
    """How often a session renewed, and when it last did."""
    if not renewals:
        return "Not yet"
    return f"{counted(len(renewals), 'time')}, {format_relative_time(renewals[-1])}"


def _renewal_facts(renewals: list[datetime]) -> list[tuple[str, Any]]:
    """A session's renewals by the clock (a burst reads apart there), the
    latest first; past what the list shows, the range says how far back."""
    latest = [at.strftime(CLOCK) for at in reversed(renewals[-RENEWALS_SHOWN:])]
    if len(renewals) <= RENEWALS_SHOWN:
        return [("Renewals", latest)]
    first, last = renewals[0].strftime(CLOCK), renewals[-1].strftime(CLOCK)
    times = counted(len(renewals), "time")
    return [("Renewed", f"{times}, {first} to {last}"), ("Latest renewals", latest)]


def _ended_rows(
    sessions: list[SessionHistory], people: dict[int, User]
) -> list[dict[str, Any]]:
    """The latest sign-ins that ended in the last week, whose, and how."""
    ended = [session for session in sessions if session.ended]
    ended.sort(key=lambda session: session.ended_at or session.signed_in, reverse=True)
    return [
        {
            "user": _who(people, session.user_id),
            "device": _device(session),
            "signed_in": format_relative_time(session.signed_in),
            "ended": format_relative_time(session.ended_at),
            "how": ENDED[session.ended],
        }
        for session in ended[:ENDED_SHOWN]
    ]


def _name(people: dict[int, User], user_id: int) -> str:
    """A user by name, or as gone when no account has that id any more."""
    user = people.get(user_id)
    return user.display_name if user else "Deleted user"


def _sessions_of(user_id: int) -> str:
    """Sessions, narrowed to one user's."""
    return with_query(SESSIONS, user=user_id)


def _who(people: dict[int, User], user_id: int) -> dict[str, str]:
    """A session's user: named, linking to their sessions."""
    return {"label": _name(people, user_id), "url": _sessions_of(user_id)}


def _matches(user: User | None, q: str) -> bool:
    """Whether a search names this user, by name or email."""
    return user is not None and row_matches(q, (user.email, user.full_name))


def _may_sign_out(session: SessionHistory, viewer: User, current: str | None) -> bool:
    """Whether the viewer may sign this session out here: a live one that is
    not this browser's (that is the Sign out link), their own, or anyone's
    for whoever administers users (the API's own rule)."""
    return (
        not session.ended
        and session.id != current
        and (session.user_id == viewer.id or may_admin_users(viewer))
    )


def _picked(value: str | None) -> int | None:
    """The user the sessions narrow to (``?user=``), if any."""
    return int(value) if value and value.isdigit() else None


def _device(session: SessionHistory) -> dict[str, str | None]:
    """A device by its browser and system, and its whole string for hover."""
    return {
        "label": ui_auth.device_label(session.user_agent),
        "full": session.user_agent,
    }


def _cookie(expires: datetime | None) -> str | None:
    """When this browser's session cookie renews from the refresh token."""
    if expires is None:
        return None
    left = format_span((expires - datetime.now(UTC)).total_seconds())
    return f"Session cookie runs out in {left}, then renews from the refresh token"


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
        rows = (
            _user_rows(
                await load_users(req.db),
                await load_session_counts(req.db),
                req.viewer,
            )
            if available and allowed
            else []
        )
        return {
            "available": available,
            "allowed": allowed,
            "can_admin": may_admin_users(req.viewer),
            "users": rows,
            "partials": PARTIALS,
        }
    if section == "sessions":
        return await _sessions_context(req, available, metadata)
    return {}


async def _sessions_context(
    req: SectionRequest, available: bool, metadata: dict[str, Any]
) -> dict[str, Any]:
    """The sessions the viewer may see (everyone's, for an administrator):
    narrowed to one user (``?user=``, a name's link) or by a search of
    users' names and emails (``?q=``), a page at a time."""
    viewer, query = req.viewer, req.query
    # ponytail: reads every kept token row, then pages in Python; page in SQL
    # (by family, newest use first) if a deployment's sessions outgrow that.
    found = await load_history(req.db, viewer) if available else []
    ids = sorted({session.user_id for session in found})
    people = await load_people(req.db, ids) if ids else {}
    who, q = _picked(query.get("user")), (query.get("q") or "").strip()
    shown = [
        session
        for session in found
        if (who is None or session.user_id == who)
        and (not q or _matches(people.get(session.user_id), q))
    ]
    live = [session for session in shown if not session.ended]
    page = page_number(query.get("page"))
    start = (page - 1) * PAGE_SIZE
    return {
        "available": available,
        "sessions": _session_rows(
            live[start : start + PAGE_SIZE],
            viewer,
            people,
            req.session_id,
            req.session_expires,
        ),
        "pager": pager(
            SESSIONS, page, PAGE_SIZE, len(live), user=query.get("user"), q=q
        ),
        "ended": _ended_rows(shown, people),
        "own_sessions": sum(1 for s in found if s.user_id == viewer.id and not s.ended),
        "showing": _name(people, who) if who is not None else None,
        "q": q,
        "lifetimes": _lifetimes(metadata),
        "partials": PARTIALS,
    }


def _user_confirmation(action: str, user: UserResponse) -> dict[str, str]:
    base = f"/api/v1/auth/users/{user.id}"
    if action == "delete":
        title, body = ui_auth.delete_user_confirmation(user.email)
        return {
            "title": title,
            "body": body,
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


def _session_confirmation(session: SessionHistory, viewer: User) -> dict[str, str]:
    """Signing out one session: the viewer's own through their sessions
    route, anyone else's through the administrators', scoped to its user."""
    title, body = ui_auth.revoke_session_confirmation(session.user_agent)
    mine = session.user_id == viewer.id
    return {
        "title": title,
        "body": body,
        "method": "delete",
        "url": f"/api/v1/auth/sessions/{session.id}"
        if mine
        else f"/api/v1/auth/users/{session.user_id}/sessions/{session.id}",
        "label": "Sign out",
        "done": "Device signed out",
    }


async def _everywhere_confirmation(
    target: str, viewer: User, db: AsyncSession
) -> dict[str, str] | None:
    """Signing another user out of every session (an account taken over),
    for whoever administers users. The viewer's own is "everywhere else"."""
    who = _picked(target)
    if who is None or who == viewer.id or not may_admin_users(viewer):
        return None
    user = (await load_people(db, [who])).get(who)
    if user is None:
        return None
    name = user.display_name
    return {
        "title": "Sign out everywhere",
        "body": f"Sign {name} out of every device? Each is signed out on its "
        "next request.",
        "method": "delete",
        "url": f"/api/v1/auth/users/{who}/sessions",
        "label": "Sign out everywhere",
        "done": f"Signed {name} out everywhere",
    }


async def confirmation(
    action: str,
    target: str,
    auth: ComponentStatus,
    viewer: User,
    db: AsyncSession,
    current: str | None = None,
) -> dict[str, str] | None:
    """The confirmation for one action, or None if it or its target is
    unknown or not the viewer's to take; ``current`` is this browser's
    session."""
    if action in ("activate", "deactivate", "delete"):
        user = next((u for u in await load_users(db) if str(u.id) == target), None)
        return _user_confirmation(action, user) if user else None
    if action == "revoke":
        session = await load_session(db, target)
        if session is None or not _may_sign_out(session, viewer, current):
            return None
        return _session_confirmation(session, viewer)
    if action == "revoke-user":
        return await _everywhere_confirmation(target, viewer, db)
    if action == "revoke-others" and target == "all":
        return {
            "title": "Sign out everywhere else",
            "body": "Sign out all your other devices? Each is signed out on its next request.",
            "method": "delete",
            "url": "/api/v1/auth/sessions",
            "label": "Sign out others",
            "done": "Signed out other devices",
        }
    return None
