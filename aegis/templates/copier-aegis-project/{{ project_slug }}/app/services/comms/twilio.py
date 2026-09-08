"""The Twilio client and credential checks the SMS and voice channels share.

``settings`` is passed in rather than imported so each channel module
keeps owning its configuration surface (and its tests keep patching it
in one place).
"""

from __future__ import annotations

from typing import Any

from twilio.rest import Client

CREDENTIALS_HELP = (
    "Twilio credentials not set. "
    "Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN environment variables. "
    "Sign up at https://www.twilio.com/try-twilio"
)


def twilio_client(settings: Any, error: type[Exception]) -> Client:
    """A configured REST client, or ``error`` naming the missing credentials."""
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        raise error(CREDENTIALS_HELP)
    return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


def credential_errors(settings: Any) -> list[str]:
    """Configuration errors for the two credentials every channel needs."""
    errors: list[str] = []
    if not settings.TWILIO_ACCOUNT_SID:
        errors.append(
            "TWILIO_ACCOUNT_SID is not set. Find it in your Twilio Console dashboard."
        )
    if not settings.TWILIO_AUTH_TOKEN:
        errors.append(
            "TWILIO_AUTH_TOKEN is not set. Find it in your Twilio Console dashboard."
        )
    return errors
