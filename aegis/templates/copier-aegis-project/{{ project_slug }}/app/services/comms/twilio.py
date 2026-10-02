"""The Twilio client and credential checks the SMS and voice channels share.

Every Twilio setting is read at once (``twilio_config``) through
``app.core.secrets``: ``.env`` first, then the secrets store when the stack
has one, so a token saved in the Overseer takes effect on the next send.
"""

from __future__ import annotations

from twilio.rest import Client

from app.core import secrets
from app.core.secrets import Secret, SecretUncheckedError, probe


async def _verify_token(token: str) -> None:
    """Fetching the account checks the token against the SID it belongs to."""
    sid = await secrets.get("TWILIO_ACCOUNT_SID")
    if not sid:
        raise SecretUncheckedError("set TWILIO_ACCOUNT_SID first.")
    await probe(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json", auth=(sid, token)
    )


# What the SMS and voice channels read through this module
# (``app.core.secrets``); the SIDs and the number are identifiers, safe to
# show whole.
SECRETS = (
    Secret("TWILIO_ACCOUNT_SID", owner="Twilio", label="Account SID", secret=False),
    Secret(
        "TWILIO_AUTH_TOKEN", owner="Twilio", label="Auth token", verify=_verify_token
    ),
    Secret("TWILIO_PHONE_NUMBER", owner="Twilio", label="From number", secret=False),
    Secret(
        "TWILIO_MESSAGING_SERVICE_SID",
        owner="Twilio",
        label="Messaging service",
        secret=False,
    ),
)

CREDENTIALS_HELP = (
    "Twilio credentials not set. "
    "Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN environment variables. "
    "Sign up at https://www.twilio.com/try-twilio"
)


TWILIO_KEYS = (
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "TWILIO_MESSAGING_SERVICE_SID",
)


async def twilio_config() -> dict[str, str | None]:
    """Every Twilio setting, read now (``.env``, then the secrets store)."""
    return await secrets.get_many(*TWILIO_KEYS)


def twilio_client(config: dict[str, str | None], error: type[Exception]) -> Client:
    """A configured REST client, or ``error`` naming the missing credentials."""
    sid, token = config["TWILIO_ACCOUNT_SID"], config["TWILIO_AUTH_TOKEN"]
    if not sid or not token:
        raise error(CREDENTIALS_HELP)
    return Client(sid, token)


def credential_errors(config: dict[str, str | None]) -> list[str]:
    """Configuration errors for the two credentials every channel needs."""
    errors: list[str] = []
    if not config["TWILIO_ACCOUNT_SID"]:
        errors.append(
            "TWILIO_ACCOUNT_SID is not set. Find it in your Twilio Console dashboard."
        )
    if not config["TWILIO_AUTH_TOKEN"]:
        errors.append(
            "TWILIO_AUTH_TOKEN is not set. Find it in your Twilio Console dashboard."
        )
    return errors
