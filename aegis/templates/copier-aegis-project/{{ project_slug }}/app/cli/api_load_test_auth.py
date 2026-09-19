"""Signing the generated requests in, when the app requires it."""

from __future__ import annotations

import asyncio
import sys

from app.cli import theme


def _get_auth_dependency() -> object | None:
    """Return the project's auth dependency callable, or ``None`` if the
    auth service isn't installed in this stack. Used to populate the
    ``AUTH`` column in ``list``."""
    try:
        from app.services.auth.deps import get_current_active_user

        return get_current_active_user
    except ImportError:
        return None


console = theme.console()


_LOAD_TEST_USER_EMAIL = "loadtest@example.com"


def apply_auto_auth(
    headers: dict[str, str],
    *,
    as_admin: bool,
    as_user: bool,
    anon: bool,
    quiet: bool,
) -> str | None:
    """Inject a bearer token into ``headers`` so auth-gated routes work
    without manual login, and return the role used (for the result record).

    Auth is automatic by default: ``admin`` when ``ADMIN_USER_EMAILS`` is
    configured (so it clears ``require_admin``), otherwise a regular user,
    otherwise anonymous when the auth service isn't installed. ``--anon``
    disables it; ``--as-admin`` / ``--as-user`` force a role. An explicit
    ``--header Authorization`` always wins and is never overwritten. The token
    is signed with the project ``SECRET_KEY`` and the user lives in the project
    DB, so it validates against in-process and locally running servers sharing
    this ``.env``.
    """
    if sum((as_admin, as_user, anon)) > 1:
        console.print(
            "Pass only one of --as-admin / --as-user / --anon.", style=theme.ERROR
        )
        sys.exit(2)
    if anon or any(k.lower() == "authorization" for k in headers):
        return None

    try:
        from app.core.config import settings
        from app.core.security import create_access_token
    except ImportError:
        if as_admin or as_user:
            console.print(
                "Auth is not installed in this stack; --as-admin/--as-user "
                "are unavailable.",
                style=theme.ERROR,
            )
            sys.exit(2)
        return None

    has_allowlist = bool(settings.ADMIN_USER_EMAILS)
    if as_admin and not has_allowlist:
        console.print(
            "--as-admin needs ADMIN_USER_EMAILS set in .env, e.g. "
            'ADMIN_USER_EMAILS=["you@example.com"].',
            style=theme.ERROR,
        )
        sys.exit(2)

    use_admin = as_admin or (not as_user and has_allowlist)
    email = settings.ADMIN_USER_EMAILS[0] if use_admin else _LOAD_TEST_USER_EMAIL
    role = "admin" if use_admin else "user"

    asyncio.run(_ensure_active_verified_user(email))
    headers["Authorization"] = f"Bearer {create_access_token({'sub': email})}"
    if not quiet:
        theme.label(f"Authenticating as {role} ({email}); pass --anon to disable")
    return role


async def _ensure_active_verified_user(email: str) -> None:
    """Create the load-test user if absent, and ensure it is active and
    verified so it satisfies ``get_current_active_user`` and ``require_admin``.
    """
    import secrets

    from app.core.db import get_async_session
    from app.models.user import UserCreate
    from app.services.auth.users import UserService

    async with get_async_session() as session:
        user_service = UserService(session)
        user = await user_service.get_user_by_email(email)
        if user is None:
            user = await user_service.create_user(
                UserCreate(
                    email=email,
                    full_name="Load Test",
                    password=secrets.token_urlsafe(16),
                )
            )
        user.is_active = True
        user.is_verified = True
        session.add(user)
        await session.commit()
