"""Proving the address belongs to them."""

from datetime import timedelta
import secrets

from sqlmodel import select

from app.core.config import settings
from app.core.time import utcnow
from app.models.user import EmailVerificationToken
from app.services.auth.user_service_base import (
    UserServiceBase,
)


class VerificationMixin(UserServiceBase):
    async def create_email_verification_token(self, user_id: int) -> str:
        """Create an email verification token for a user.

        Invalidates any previously-issued unused tokens for this user first,
        so a resend immediately locks out the old link. Prevents an
        intercepted email from remaining live after the user hits "Resend".
        Returns the new token string.
        """
        await self._invalidate_prior_email_verification_tokens(user_id)

        token = secrets.token_urlsafe(32)
        verification_token = EmailVerificationToken(user_id=user_id, token=token)
        self.db.add(verification_token)
        await self.db.commit()
        return token

    async def _invalidate_prior_email_verification_tokens(self, user_id: int) -> None:
        """Mark all unused email-verification tokens for this user as used.

        Called whenever a fresh token is about to be issued.
        """
        stmt = select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user_id,
            EmailVerificationToken.used == False,  # noqa: E712
        )
        result = await self.db.exec(stmt)
        for tok in result.all():
            tok.used = True
            self.db.add(tok)

    async def verify_email(self, token: str) -> None:
        """Verify a user's email using a valid verification token.

        Sets user.is_verified=True and marks the token as used.
        Raises ValueError if the token is invalid, expired, or already used.
        """
        statement = select(EmailVerificationToken).where(
            EmailVerificationToken.token == token,
            EmailVerificationToken.used == False,  # noqa: E712
        )
        result = await self.db.exec(statement)
        verification_token = result.first()

        if not verification_token:
            raise ValueError("Invalid or expired token")

        # Check expiry
        now = utcnow()
        expires_at = verification_token.created_at + timedelta(
            hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS
        )
        if expires_at < now:
            raise ValueError("Invalid or expired token")

        # Set user as verified
        user = await self.get_user_by_id(verification_token.user_id)
        if not user:
            raise ValueError("Invalid or expired token")

        user.is_verified = True
        self.db.add(user)

        # Mark token as used
        verification_token.used = True
        self.db.add(verification_token)

        await self.db.commit()
