"""Passwords, sign-in, and the lockout that follows failures."""

from datetime import timedelta
import secrets

from sqlmodel import select

from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.core.time import utcnow
from app.models.user import PasswordResetToken, User
from app.services.auth.user_service_base import (
    UserServiceBase,
)


class PasswordsMixin(UserServiceBase):
    async def create_password_reset_token(self, email: str) -> str | None:
        """Create a password reset token for a user.

        Returns the token string if the user exists, None otherwise.
        Callers should not reveal whether the user exists.
        """
        email = email.lower()
        user = await self.get_user_by_email(email)
        if not user:
            return None

        token = secrets.token_urlsafe(32)
        reset_token = PasswordResetToken(user_id=user.id, token=token)
        self.db.add(reset_token)
        await self.db.commit()
        return token

    async def reset_password(self, token: str, new_password: str) -> None:
        """Reset a user's password using a valid reset token.

        Raises ValueError if the token is invalid, expired, or already used.
        """
        statement = select(PasswordResetToken).where(
            PasswordResetToken.token == token,
            PasswordResetToken.used == False,  # noqa: E712
        )
        result = await self.db.exec(statement)
        reset_token = result.first()

        if not reset_token:
            raise ValueError("Invalid or expired token")

        # Check expiry
        now = utcnow()
        expires_at = reset_token.created_at + timedelta(
            minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES
        )
        if expires_at < now:
            raise ValueError("Invalid or expired token")

        # Update password
        user = await self.get_user_by_id(reset_token.user_id)
        if not user:
            raise ValueError("Invalid or expired token")

        user.hashed_password = get_password_hash(new_password)
        self.db.add(user)

        # Mark token as used
        reset_token.used = True
        self.db.add(reset_token)

        # Revoke every live refresh token for this user as part of the
        # same transaction: password change, token-used flag, and
        # revoke commit together or not at all. Otherwise a revoke
        # failure leaves the password changed and the reset token
        # consumed while the response 500s, blocking retry.
        from app.services.auth.refresh_tokens import RefreshService

        await RefreshService(self.db).revoke_all_for_user(reset_token.user_id)

        await self.db.commit()

    async def change_password(
        self, user_id: int, current_password: str, new_password: str
    ) -> bool:
        """Verify the caller's current password and set a new one.

        Returns ``False`` if the current password is wrong so the API can
        surface a 400 without leaking internal state. Raises ``ValueError``
        if the user doesn't exist (caller's auth context got us here, so
        this is an invariant violation, not a normal flow).
        """
        user = await self.get_user_by_id(user_id)
        if user is None:
            raise ValueError("User not found")

        if not verify_password(current_password, user.hashed_password):
            return False

        user.hashed_password = get_password_hash(new_password)
        self.db.add(user)
        await self.db.commit()
        return True

    async def authenticate_credentials(
        self, email: str, password: str
    ) -> tuple[User | None, str | None]:
        """Validate email + password and return the user on success.

        Shared between the API ``/token`` endpoint and any web ``/login``
        form handler so both paths stay in lockstep (lockout, failed-attempt
        counters, last_login bump). Callers own rate-limiting and audit
        emission — those vary by entry point.

        Returns ``(user, None)`` on success, or ``(None, "locked" | "invalid")``
        on failure. The error string lets the caller choose 403 vs 401 or a
        redirect destination without re-implementing the check.
        """
        user = await self.get_user_by_email(email)

        if user and await self.is_account_locked(user):
            return None, "locked"

        if not user or not verify_password(password, user.hashed_password):
            if user:
                await self.record_failed_login(email)
            return None, "invalid"

        await self.reset_login_attempts(user.id)
        await self.update_user(user.id, last_login=utcnow())
        return user, None

    async def record_failed_login(self, email: str) -> None:
        """Increment failed login attempts and lock account if threshold reached."""
        user = await self.get_user_by_email(email)
        if not user:
            return

        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.ACCOUNT_LOCKOUT_ATTEMPTS:
            user.locked_until = utcnow() + timedelta(
                minutes=settings.ACCOUNT_LOCKOUT_MINUTES
            )

        self.db.add(user)
        await self.db.commit()

    async def reset_login_attempts(self, user_id: int) -> None:
        """Reset failed login attempts and unlock account."""
        user = await self.get_user_by_id(user_id)
        if not user:
            return

        user.failed_login_attempts = 0
        user.locked_until = None
        self.db.add(user)
        await self.db.commit()

    async def is_account_locked(self, user: User) -> bool:
        """Check if an account is currently locked.

        If locked_until is in the past, auto-unlock, persist to DB, and return False.
        """
        if user.locked_until is None:
            return False

        now = utcnow()
        if user.locked_until > now:
            return True

        # Auto-unlock: lockout has expired — persist to DB
        user.failed_login_attempts = 0
        user.locked_until = None
        self.db.add(user)
        await self.db.commit()
        return False
