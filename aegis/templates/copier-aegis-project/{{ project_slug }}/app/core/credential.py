"""``Credential``: type a ``Settings`` field with it to list the key on the
Overseer Secrets page, with no other declaration.

    SENDGRID_API_KEY: Credential = None

The value is still a plain ``str`` (``settings.SENDGRID_API_KEY`` reads as
before). A key read through ``settings`` only ever sees ``.env``, so it is
listed read-only; code that reads it with ``await secrets.get(name)``
declares it in ``SECRETS`` instead, which makes it settable while the app
runs (``app.core.secrets``). Its own module so ``config`` can use it
without importing ``secrets``, which imports ``config``.

``shown`` keeps every credential out of a ``Settings`` repr (a log line, a
traceback, a failing assert): a field named like one, and a URL's password.
``tests/test_secrets.py`` holds every declared credential to the names.
"""

from collections.abc import Iterable
from typing import Annotated, Any

HIDDEN_SUFFIXES = ("_KEY", "_SECRET", "_TOKEN", "_PASSWORD")


class CredentialMarker:
    """The annotation ``app.core.secrets`` looks for on ``Settings`` fields."""


CREDENTIAL = CredentialMarker()
Credential = Annotated[str | None, CREDENTIAL]


def hide_password(url: str) -> str:
    """``url`` with its password, if any, as ``***``: a user's and a bare
    one (``redis://:pw@host``), whatever characters it holds. The one rule
    for showing a connection URL (``Settings``' repr, Overseer's pages)."""
    scheme, sep, rest = url.partition("://")
    if not sep:
        return url
    head, query_sep, tail = rest.partition("?")
    credentials, at, host = head.rpartition("@")
    if not at or ":" not in credentials:
        return url
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}{query_sep}{tail}"


def shown(fields: Iterable[tuple[str | None, Any]]) -> list[tuple[str | None, Any]]:
    """A model's ``__repr_args__`` without a credential's value."""
    return [
        (name, hide_password(value) if isinstance(value, str) else value)
        for name, value in fields
        if not (name or "").endswith(HIDDEN_SUFFIXES)
    ]
