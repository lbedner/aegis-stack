"""Credentials behind one interface: ``await get(name)``.

Every project has this. ``.env`` (with the process environment) is the
zero-setup backend: read-only, and a value changes on restart. A writable
store, the secrets component, plugs in behind the same calls
(``set_store``), the way object storage sits behind ``app.core.storage``.
A value set in ``.env`` wins over a stored one and is read-only elsewhere.

Names are the settings' own (``RESEND_API_KEY``), so one name works in
``.env``, in ``Settings`` and in the store. The code that reads a credential
declares it beside itself, as ``SECRETS = (Secret(...), ...)`` in a module
listed in ``OWNERS``, like ``REDIS_KEYS``.

Values are write-only from the outside: ``get`` hands one to the code that
uses it, and everything else (``status``, the Overseer page) sees where it is
set, its last four characters and when, never the value.
"""

from dataclasses import dataclass
from datetime import datetime
from functools import cache
from importlib import import_module
from typing import Literal, Protocol

from app.core.config import settings

# Modules that declare ``SECRETS``. Absent ones (a service this stack does
# not have) are skipped.
OWNERS = (
    "app.services.ai.domains.llm.provider_management",
    "app.services.comms.email",
    "app.services.comms.twilio",
    "app.services.payment.providers.stripe",
    "app.components.backend.api.auth.oauth",
)
# Shorter than this, the last four characters are most of the value.
HINT_MIN_LENGTH = 12

Source = Literal["env", "database"]


@dataclass(frozen=True)
class Secret:
    """A credential some code reads. ``secret=False`` marks provider config
    that is safe to show whole (a from address, a phone number); it lives
    in the same store so a connection can be finished in one place."""

    name: str
    owner: str
    label: str = ""
    secret: bool = True


@dataclass(frozen=True)
class StoredSecret:
    """What a writable store keeps beside a value, readable without it."""

    hint: str | None
    set_at: datetime | None = None
    set_by: str | None = None


@dataclass(frozen=True)
class SecretStatus:
    """One declared secret as anyone but its reader may see it."""

    name: str
    owner: str
    label: str
    secret: bool
    source: Source | None
    hint: str | None
    set_at: datetime | None = None
    set_by: str | None = None

    @property
    def is_set(self) -> bool:
        return self.source is not None


class SecretStore(Protocol):
    """A writable backend (the secrets component's encrypted table)."""

    async def get(self, name: str) -> str | None: ...

    async def put(self, name: str, value: str, actor: str) -> None: ...

    async def stored(self) -> dict[str, StoredSecret]: ...


class SecretsReadOnlyError(Exception):
    """A write this backend cannot take, with the reason to show."""


class UnknownSecretError(ValueError):
    """A name no installed code declares."""


_store: SecretStore | None = None


def set_store(store: SecretStore | None) -> None:
    """Install the writable backend (or remove it, with None)."""
    global _store
    _store = store


def writable() -> bool:
    """Whether a store is installed, so values can be set here at all."""
    return _store is not None


def collect() -> tuple[Secret, ...]:
    """Every secret the installed owners declare, in ``OWNERS`` order; the
    first declaration of a name wins."""
    found: dict[str, Secret] = {}
    for path in OWNERS:
        try:
            module = import_module(path)
        except ImportError:
            continue
        for entry in getattr(module, "SECRETS", ()):
            found.setdefault(entry.name, entry)
    return tuple(found.values())


@cache
def declared() -> tuple[Secret, ...]:
    """``collect``, once per process: declarations are code."""
    return collect()


def _from_env(name: str) -> str | None:
    """What ``Settings`` loaded for ``name`` (``.env`` and the environment)."""
    value = getattr(settings, name, None)
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):  # a pydantic SecretStr
        value = value.get_secret_value()
    return str(value).strip() or None


async def get(name: str) -> str | None:
    """The value for ``name``, resolved now: ``.env`` first, then the store."""
    if (value := _from_env(name)) is not None:
        return value
    return await _store.get(name) if _store is not None else None


async def put(name: str, value: str, actor: str) -> None:
    """Store ``value`` for a declared ``name``, or refuse with the reason."""
    if name not in {s.name for s in declared()}:
        raise UnknownSecretError(f"{name} is not a declared secret.")
    if _from_env(name) is not None:
        raise SecretsReadOnlyError(f"{name} is set in .env, which wins: change it there.")
    if _store is None:
        raise SecretsReadOnlyError(
            f"No writable backend: set {name} in .env, or add the secrets component."
        )
    await _store.put(name, value, actor)


def _hint(entry: Secret, value: str) -> str | None:
    if not entry.secret:
        return value
    return value[-4:] if len(value) >= HINT_MIN_LENGTH else None


def _row(
    entry: Secret,
    source: Source | None = None,
    hint: str | None = None,
    kept: StoredSecret | None = None,
) -> SecretStatus:
    return SecretStatus(
        name=entry.name,
        owner=entry.owner,
        label=entry.label,
        secret=entry.secret,
        source=source,
        hint=hint,
        set_at=kept.set_at if kept else None,
        set_by=kept.set_by if kept else None,
    )


async def status() -> list[SecretStatus]:
    """Every declared secret: where it is set, its hint, when and by whom."""
    stored = await _store.stored() if _store is not None else {}
    rows = []
    for entry in declared():
        if (value := _from_env(entry.name)) is not None:
            rows.append(_row(entry, "env", _hint(entry, value)))
        elif (kept := stored.get(entry.name)) is not None:
            rows.append(_row(entry, "database", kept.hint, kept))
        else:
            rows.append(_row(entry))
    return rows
