"""Guest sign-in: one shared account anyone may walk into, a session per
visitor (``auth[guest]``).

Nobody signs up. Each "Continue as guest" starts its own session on the
one guest user, with ``source="guest"`` and a short lifetime
(``GUEST_SESSION_HOURS``), so expiry, revocation and the Sessions page are
the ones every sign-in has. Visitors on the account are told apart by
session, never by user: a guest sees and ends only its own session, and
what it owns elsewhere (its chats, its spend) is keyed by ``visitor``.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError

from app.core.visitor import GUEST_EMAIL, guest_visitor
from app.models.user import User, UserCreate

if TYPE_CHECKING:
    from app.services.auth.domains.users.accounts import UserService

__all__ = ["guest_user", "is_guest", "visitor"]

def is_guest(user: User) -> bool:
    """Whether ``user`` is the shared guest account."""
    return user.email == GUEST_EMAIL


def visitor(user: User, session_id: str | None) -> str:
    """Who a request is, for what it owns (``app.core.visitor``): a guest
    by its session, anyone else by user id."""
    if is_guest(user) and session_id:
        return guest_visitor(session_id)
    return str(user.id)


async def guest_user(users: UserService) -> User:
    """The guest account, made on first use. Its password is random and
    kept nowhere, so it can only be signed in to as a guest."""
    found = await users.get_user_by_email(GUEST_EMAIL)
    if found is not None:
        return found
    try:
        # Built unvalidated: ``UserCreate`` refuses this email to everyone else.
        made = await users.create_user(
            UserCreate.model_construct(
                email=GUEST_EMAIL, full_name="Guest", password=secrets.token_urlsafe(32)
            )
        )
    except IntegrityError:  # two first visitors at once: the other made it
        await users.db.rollback()
        if (found := await users.get_user_by_email(GUEST_EMAIL)) is None:
            raise
        return found
    # Nothing to verify.
    return await users.update_user(made.id, is_verified=True) or made
