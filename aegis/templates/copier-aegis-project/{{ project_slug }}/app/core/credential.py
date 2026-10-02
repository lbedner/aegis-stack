"""``Credential``: type a ``Settings`` field with it to list the key on the
Overseer Secrets page, with no other declaration.

    SENDGRID_API_KEY: Credential = None

The value is still a plain ``str`` (``settings.SENDGRID_API_KEY`` reads as
before). A key read through ``settings`` only ever sees ``.env``, so it is
listed read-only; code that reads it with ``await secrets.get(name)``
declares it in ``SECRETS`` instead, which makes it settable while the app
runs (``app.core.secrets``). Its own module so ``config`` can use it
without importing ``secrets``, which imports ``config``.
"""

from typing import Annotated


class CredentialMarker:
    """The annotation ``app.core.secrets`` looks for on ``Settings`` fields."""


CREDENTIAL = CredentialMarker()
Credential = Annotated[str | None, CREDENTIAL]
