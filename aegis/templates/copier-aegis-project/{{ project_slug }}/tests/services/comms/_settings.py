"""``secret_settings`` with every comms key blanked first."""

from contextlib import AbstractContextManager
from typing import Any

from tests._secret_settings import secret_settings as _secret_settings

COMMS_KEYS = (
    "RESEND_API_KEY",
    "RESEND_FROM_EMAIL",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "TWILIO_MESSAGING_SERVICE_SID",
)


def secret_settings() -> AbstractContextManager[Any]:
    return _secret_settings(*COMMS_KEYS)
