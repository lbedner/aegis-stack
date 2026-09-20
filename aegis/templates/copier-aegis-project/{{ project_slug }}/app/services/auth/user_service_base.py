"""Shared state for the user-service mixins."""

from typing import TYPE_CHECKING, Any

from sqlmodel.ext.asyncio.session import AsyncSession


class RegistrationClosedError(Exception):
    """Raised by ``upsert_from_oauth`` when a brand-new user attempts to
    sign in via OAuth and ``settings.REGISTRATION_ENABLED`` is False.

    Exists so the OAuth callback can translate this into a friendly
    redirect (``/login?oauth_error=signup_closed``) instead of a 500.
    Existing users who already have an OAuthIdentity link, or whose
    email matches an existing local account, sign in normally.
    """


class RestoreConflictError(Exception):
    """Raised by ``restore_user`` when the soft-deleted user's email is
    already held by another live user. The partial unique index
    ``ix_user_email`` allows re-registration after a soft delete, so
    blindly clearing ``deleted_at`` could produce two live rows with the
    same email — a constraint violation. The endpoint layer translates
    this into a 409.
    """


class UserServiceBase:
    """The session every user-service mixin reads, and the core reads
    they call back into.

    ``UserService.__init__`` assigns ``db``; the methods named here live
    on the core class. Declaring them lets each mixin module type check
    on its own, and tests/core/test_mixin_declarations.py is what keeps
    the declaration honest.
    """

    db: AsyncSession

    if TYPE_CHECKING:

        async def get_user_by_email(self, *args: Any, **kwargs: Any) -> Any: ...
        async def get_user_by_id(self, *args: Any, **kwargs: Any) -> Any: ...
        async def update_user(self, *args: Any, **kwargs: Any) -> Any: ...
