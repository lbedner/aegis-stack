"""Settings for a test, set where ``app.core.secrets`` reads them.

Code that reads a key through ``secrets.get`` / ``get_many`` sees ``.env``
(the real ``settings``) and then the secrets store, so patching a module's
own ``settings`` no longer reaches it. ``secret_settings(*names)`` blanks
those names, uses no store, and writes whatever the test assigns onto the
real settings, restoring both afterwards.

    with secret_settings("STRIPE_SECRET_KEY") as s:
        s.STRIPE_SECRET_KEY = "sk_test_fake"
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.core import secrets
from app.core.config import settings


class _Assigner:
    def __init__(self, saved: dict[str, Any]) -> None:
        object.__setattr__(self, "_saved", saved)

    def __setattr__(self, name: str, value: Any) -> None:
        self._saved.setdefault(name, settings.__dict__.get(name))
        settings.__dict__[name] = value


@contextmanager
def secret_settings(*names: str) -> Iterator[Any]:
    saved: dict[str, Any] = {}
    store, discovered = secrets._store, secrets._discovered
    secrets.set_store(None)
    assigner = _Assigner(saved)
    for name in names:
        setattr(assigner, name, None)
    try:
        yield assigner
    finally:
        settings.__dict__.update(saved)
        secrets._store, secrets._discovered = store, discovered
