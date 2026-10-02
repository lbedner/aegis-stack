"""The Porkbun key pair the DNS setup reads, declared for
``app.core.secrets`` (the Secrets page lists them) with the check that tells
a working pair from a typo. Beside ``porkbun.py`` rather than in it, so the
adapter keeps to its own job.
"""

from typing import Any

from app.core import secrets
from app.core.secrets import Secret, SecretUncheckedError, probe

from .porkbun import PORKBUN_BASE_URL, PORKBUN_KEYS


def _verify_pair(name: str) -> Any:
    """A check for one half of the key pair: Porkbun's ping needs both."""

    async def verify(value: str) -> None:
        keys = await secrets.get_many(*PORKBUN_KEYS) | {name: value}
        missing = [key for key, val in keys.items() if not val]
        if missing:
            raise SecretUncheckedError(f"set {missing[0]} first.")
        await probe(
            f"{PORKBUN_BASE_URL}/ping",
            json={
                "apikey": keys["PORKBUN_API_KEY"],
                "secretapikey": keys["PORKBUN_SECRET_KEY"],
            },
            rejected=(400, 401, 403),
            passes=lambda r: r.is_success and r.json().get("status") == "SUCCESS",
        )

    return verify


# What the DNS setup reads (``app.core.secrets``).
SECRETS = (
    Secret(
        "PORKBUN_API_KEY",
        owner="DNS (Porkbun)",
        label="API key",
        verify=_verify_pair("PORKBUN_API_KEY"),
    ),
    Secret(
        "PORKBUN_SECRET_KEY",
        owner="DNS (Porkbun)",
        label="Secret key",
        verify=_verify_pair("PORKBUN_SECRET_KEY"),
    ),
)
