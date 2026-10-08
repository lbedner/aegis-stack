"""Signing the generated requests in, when the app requires it."""

from __future__ import annotations

import asyncio
import sys

from app.cli import theme
from app.services.load_test.api.auth import (
    ADMIN,
    USER,
    admin_available,
    auth_installed,
    bearer_header,
    email_for,
)


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

    if not auth_installed():
        if as_admin or as_user:
            console.print(
                "Auth is not installed in this stack; --as-admin/--as-user "
                "are unavailable.",
                style=theme.ERROR,
            )
            sys.exit(2)
        return None

    if as_admin and not admin_available():
        console.print(
            "--as-admin needs ADMIN_USER_EMAILS set in .env, e.g. "
            'ADMIN_USER_EMAILS=["you@example.com"].',
            style=theme.ERROR,
        )
        sys.exit(2)

    role = ADMIN if as_admin or (not as_user and admin_available()) else USER
    headers.update(asyncio.run(bearer_header(role)))
    if not quiet:
        theme.label(
            f"Authenticating as {role} ({email_for(role)}); pass --anon to disable"
        )
    return role
