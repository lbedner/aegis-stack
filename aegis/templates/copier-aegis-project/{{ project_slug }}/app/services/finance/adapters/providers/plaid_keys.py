"""The Plaid key pair bank connections read, declared for
``app.core.secrets`` (the Secrets page lists them) with the check that tells
a working pair from a typo. Beside ``plaid.py`` so the client keeps to its
own job.
"""

from app.core import secrets
from app.core.config import settings
from app.core.secrets import Secret, probe

from .plaid import _ENV_HOSTS


async def _verify_secret(secret: str) -> None:
    """One institution, fetched with the pair: Plaid answers 400
    INVALID_API_KEYS for a secret that does not match the client ID."""
    client_id = await secrets.get("PLAID_CLIENT_ID")
    if not client_id:
        raise secrets.SecretUncheckedError("set PLAID_CLIENT_ID first.")
    host = _ENV_HOSTS.get(settings.PLAID_ENV, _ENV_HOSTS["sandbox"])
    await probe(
        f"{host}/institutions/get",
        json={
            "client_id": client_id,
            "secret": secret,
            "count": 1,
            "offset": 0,
            "country_codes": ["US"],
        },
        rejected=(400, 401),
    )


# What bank connections read (``app.core.secrets``); the client ID is an
# identifier, the secret is not. Nothing without Plaid: its settings are
# not generated then.
SECRETS = (
    (
        Secret(
            "PLAID_CLIENT_ID",
            owner="Finance (Plaid)",
            label="Client ID",
            secret=False,
            needed=True,
        ),
        Secret(
            "PLAID_SECRET",
            owner="Finance (Plaid)",
            label="Secret",
            needed=True,
            verify=_verify_secret,
        ),
    )
    if settings.FINANCE_PLAID
    else ()
)
