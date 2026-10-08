"""Signing load-test requests in as a role, for the CLI's runs and Overseer's.

The token is signed with the project's ``SECRET_KEY`` for a user in the
project's database, so it validates against the app in this process and
against any server sharing this ``.env``. Without the auth service there
is no one to sign in as, and every run is anonymous.
"""

from __future__ import annotations

ADMIN = "admin"
USER = "user"
ANONYMOUS = "anonymous"
LOAD_TEST_USER_EMAIL = "loadtest@example.com"


def auth_installed() -> bool:
    """Whether this stack has accounts to sign in as."""
    try:
        import app.core.security  # noqa: F401
    except ImportError:
        return False
    return True


def admin_available() -> bool:
    """Whether an admin exists to sign in as (``ADMIN_USER_EMAILS``)."""
    from app.core.config import settings

    return auth_installed() and bool(getattr(settings, "ADMIN_USER_EMAILS", None))


def roles() -> list[str]:
    """The roles a run can sign in as here, the default first: admin when
    there is one, so admin-only routes answer; else a user; else anonymous."""
    offered = ((ADMIN, admin_available()), (USER, auth_installed()), (ANONYMOUS, True))
    return [role for role, ok in offered if ok]


def default_role() -> str:
    """The role a run signs in as unless told otherwise."""
    return roles()[0]


def email_for(role: str) -> str:
    """Who ``role`` signs in as: the first admin, or the load-test user."""
    from app.core.config import settings

    return settings.ADMIN_USER_EMAILS[0] if role == ADMIN else LOAD_TEST_USER_EMAIL


async def bearer_header(role: str) -> dict[str, str]:
    """An ``Authorization`` header signing requests in as ``role``; none
    for anonymous. Raises ``ValueError`` for a role this stack cannot be."""
    if role == ANONYMOUS:
        return {}
    if role not in roles():
        raise ValueError(f"Cannot sign in as {role} here.")
    from app.core.security import create_access_token

    email = email_for(role)
    await ensure_load_test_user(email)
    return {"Authorization": f"Bearer {create_access_token({'sub': email})}"}


async def ensure_load_test_user(email: str) -> None:
    """Create the user if absent, and make it active and verified so it
    clears ``get_current_active_user`` and ``require_admin``."""
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
