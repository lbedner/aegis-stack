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
from datetime import UTC, datetime
from typing import Any

import pytest

from app.core import saved_settings, secrets
from app.core.config import settings

SET_AT = datetime(2026, 10, 1, tzinfo=UTC)


class FakeStore:
    """A writable store, the shape the secrets component installs. Seed it
    through ``values``; a ``put`` also keeps the hint core computed and who
    wrote it."""

    name = "database"
    writable = True

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.hints: dict[str, str | None] = {}
        self.actors: list[str] = []

    async def get(self, name: str) -> str | None:
        return self.values.get(name)

    async def get_many(self, names: list[str]) -> dict[str, str | None]:
        return {name: self.values.get(name) for name in names}

    async def put(self, name: str, value: str, hint: str | None, actor: str) -> None:
        self.values[name] = value
        self.hints[name] = hint
        self.actors.append(actor)

    async def delete(self, name: str, actor: str) -> None:
        self.values.pop(name, None)

    async def stored(self) -> dict[str, secrets.StoredSecret]:
        return {
            name: secrets.StoredSecret(
                hint=self.hints.get(name, value[-4:]), set_at=SET_AT, set_by="ops"
            )
            for name, value in self.values.items()
        }


class _Assigner:
    def __init__(self, saved: dict[str, Any]) -> None:
        object.__setattr__(self, "_saved", saved)

    def __setattr__(self, name: str, value: Any) -> None:
        self._saved.setdefault(name, settings.__dict__.get(name))
        settings.__dict__[name] = value


def use_store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    """A fresh ``FakeStore`` as the store for one test; ``monkeypatch``
    puts back whatever was there."""
    store = FakeStore()
    monkeypatch.setattr(secrets, "_store", store)
    monkeypatch.setattr(secrets, "_discovered", True)
    return store


def settings_at_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every ``Configurable`` setting at its default, as if ``.env`` set
    none; any value a test applies is put back after it."""
    monkeypatch.setattr(saved_settings, "IN_ENV", frozenset())
    for entry in saved_settings.declarations():
        monkeypatch.setitem(
            settings.__dict__, entry.name, saved_settings.default_of(entry.name)
        )


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
