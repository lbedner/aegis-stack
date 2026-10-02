"""Credentials behind one interface: ``await get(name)``.

Every project has this. ``.env`` (with the process environment) is the
zero-setup backend: read-only, and a value changes on restart. A writable
store, the secrets component, plugs in behind the same calls
(``set_store``), the way object storage sits behind ``app.core.storage``.
A value set in ``.env`` wins over a stored one and is read-only elsewhere.

Names are the settings' own (``RESEND_API_KEY``), so one name works in
``.env``, in ``Settings`` and in the store. The code that reads a credential
with ``get`` declares it beside itself, as ``SECRETS = (Secret(...), ...)``
in a module listed in ``OWNERS``, like ``REDIS_KEYS``. Reading ``settings``
as usual is fine too: type the field ``Credential`` and it is listed,
read-only (``app.core.credential``).

Values are write-only from the outside: ``get`` hands one to the code that
uses it, and everything else (``status``, the Overseer page) sees where it is
set, its last four characters and when, never the value.

A declaration also says whether the app needs it (``needed``, decided by
config: the active AI provider's key, not the five it could use) and how to
check it (``verify``, one cheap call to the provider, usually ``probe``). A
value the provider refuses is never stored, so a typo fails at the paste.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from importlib import import_module
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from app.core.config import settings
from app.core.credential import CREDENTIAL
from app.core.log import logger

# Modules that declare ``SECRETS``. Absent ones (a service this stack does
# not have) are skipped.
OWNERS = (
    "app.services.ai.domains.llm.provider_management",
    "app.services.comms.email",
    "app.services.comms.twilio",
    "app.services.payment.providers.stripe",
    "app.components.backend.api.auth.oauth",
    "app.services.ops.adapters.porkbun_keys",
    "app.services.rag.config",
    "app.components.storage.s3",
    "app.services.finance.adapters.providers.plaid_keys",
    "app.services.finance.adapters.providers.snaptrade",
    "app.services.insights.adapters.collectors.base",
)
# Shorter than this, the last four characters are most of the value.
HINT_MIN_LENGTH = 12

# Where a value came from: ``.env`` and the environment, or the installed
# store's own name (``database``, later ``vault``...).
ENV = "env"
# How a source reads to a person; another store reads as its own name.
SOURCE_LABELS = {ENV: ".env", "database": "Saved here"}

# What a check found: the provider took it, refused it, or could not be asked.
VERIFIED, REJECTED, UNVERIFIED = "verified", "rejected", "unverified"
VERIFY_TIMEOUT = httpx.Timeout(8.0)


@dataclass(frozen=True)
class Secret:
    """A credential some code reads. ``secret=False`` marks provider config
    that is safe to show whole (a from address, a phone number); it lives
    in the same store so a connection can be finished in one place."""

    name: str
    owner: str
    label: str = ""
    secret: bool = True
    # Whether what is enabled reads it; a callable when config decides.
    needed: bool | Callable[[], bool] = False
    # Raises SecretRejectedError if the provider refuses ``value``, or
    # SecretUncheckedError if it cannot say; returns if it works.
    verify: Callable[[str], Awaitable[None]] | None = None
    # Values the provider itself offers (an account's phone numbers, a
    # mail provider's verified domains), as (value, label), picked instead
    # of typed. Raises like ``verify`` when the provider cannot answer.
    choices: Callable[[], Awaitable[list[tuple[str, str]]]] | None = None
    # Read with ``secrets.get``, so a stored value takes effect. False for a
    # key read through ``settings`` (a ``Credential`` field), which only
    # ever sees ``.env``: listed, never set here.
    live: bool = True
    # A ``Configurable`` setting rather than a credential
    # (``app.core.saved_settings``): its own page, its default shown, and a
    # value checked against its type: ``parse`` returns the text to store,
    # or raises SecretRejectedError.
    setting: bool = False
    default: str | None = None
    parse: Callable[[str], str] | None = None

    def is_needed(self) -> bool:
        return self.needed() if callable(self.needed) else self.needed


@dataclass(frozen=True)
class Verdict:
    """What checking a value found (``VERIFIED``...), and the words for it.
    Never carries the value."""

    result: str
    message: str


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
    source: str | None
    hint: str | None
    set_at: datetime | None = None
    set_by: str | None = None
    needed: bool = False
    verifiable: bool = False
    live: bool = True
    choosable: bool = False
    setting: bool = False
    default: str | None = None

    @property
    def is_set(self) -> bool:
        return self.source is not None

    @property
    def state(self) -> str:
        return state_label(self.source, self.needed, self.setting)

    @property
    def in_effect(self) -> str | None:
        """The value to show: the hint where set, else a setting's default."""
        return self.hint if self.is_set else self.default


def state_label(source: str | None, needed: bool = False, setting: bool = False) -> str:
    """Where a value comes from, as every surface words it. Unset: Default
    (a setting), Missing (something enabled needs it), else Not used."""
    if source is not None:
        return SOURCE_LABELS.get(source, source.capitalize())
    if setting:
        return "Default"
    return "Missing" if needed else "Not used"


class SecretStore(Protocol):
    """A backend behind ``.env``: the secrets component's encrypted table,
    or an external manager. ``name`` is what status reports as the source;
    ``writable`` is False where the app may only read (a manager's policy),
    and writes then refuse with where to change the value instead."""

    name: str
    writable: bool

    async def get(self, name: str) -> str | None: ...

    async def get_many(self, names: list[str]) -> dict[str, str | None]: ...

    async def put(
        self, name: str, value: str, hint: str | None, actor: str
    ) -> None: ...

    async def delete(self, name: str, actor: str) -> None: ...

    async def stored(self) -> dict[str, StoredSecret]: ...


class SecretsReadOnlyError(Exception):
    """A write this backend cannot take, with the reason to show."""


class UnknownSecretError(ValueError):
    """A name no installed code declares."""


class SecretUnreadableError(Exception):
    """A stored value that will not decrypt: a different ENCRYPTION_KEY, or
    a ciphertext moved from another name. Never carries the value."""


class SecretRejectedError(Exception):
    """The provider refused the credential (a typo, a revoked key)."""


class SecretUncheckedError(Exception):
    """The provider could not be asked, or gave no clear answer."""


# The secrets component's module, when this stack has it. Its ``install``
# sets the store (or explains why it cannot) the first time any process
# asks, so the webserver, worker and scheduler need no startup hook each.
STORE_MODULE = "app.components.secrets.store"

_store: SecretStore | None = None
_discovered = False


def set_store(store: SecretStore | None) -> None:
    """Install the writable backend, or none. An explicit choice wins over
    discovering the component's store."""
    global _store, _discovered
    _store, _discovered = store, True


def _active_store() -> SecretStore | None:
    global _discovered
    if not _discovered:
        _discovered = True
        try:
            module = import_module(STORE_MODULE)
        except ImportError:  # no secrets component in this stack
            return None
        module.install()
    return _store


def writable() -> bool:
    """Whether values can be set here at all: a store that takes writes."""
    store = _active_store()
    return store is not None and store.writable


def store_name() -> str | None:
    """The installed store's name (``database``, ``vault``...), or None on
    ``.env`` alone."""
    store = _active_store()
    return store.name if store is not None else None


def collect() -> tuple[Secret, ...]:
    """Every secret the installed owners declare, in ``OWNERS`` order (the
    first declaration of a name wins), then every ``Credential`` setting
    nothing declared."""
    found: dict[str, Secret] = {}
    for path in OWNERS:
        try:
            module = import_module(path)
        except ImportError:
            continue
        for entry in getattr(module, "SECRETS", ()):
            found.setdefault(entry.name, entry)
    for name, field in type(settings).model_fields.items():
        if CREDENTIAL in field.metadata:
            found.setdefault(
                name,
                Secret(name, owner="App", label=field.description or "", live=False),
            )
    from app.core import saved_settings  # it imports this module

    for entry in saved_settings.declarations():
        found.setdefault(entry.name, entry)
    return tuple(found.values())


@cache
def declared() -> tuple[Secret, ...]:
    """``collect``, once per process: declarations are code."""
    return collect()


def is_setting(name: str) -> bool:
    """Whether ``name`` is a saved setting (its own page), not a credential."""
    return any(entry.name == name and entry.setting for entry in declared())


def _from_env(name: str, source: Any = None) -> str | None:
    """What ``Settings`` loaded for ``name`` (``.env`` and the environment).
    ``source`` is a settings object handed in (a service built with its own
    settings); the app's when None. A setting at its default is not set
    there: a saved value replaces it."""
    from app.core import saved_settings  # it imports this module

    if source is None and name in saved_settings.left_at_default():
        return None
    value = getattr(settings if source is None else source, name, None)
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):  # a pydantic SecretStr
        value = value.get_secret_value()
    return str(value).strip() or None


async def get(name: str, source: Any = None) -> str | None:
    """The value for ``name``, resolved now: ``.env`` first (read from
    ``source``, a settings object, when given), then the store."""
    if (value := _from_env(name, source)) is not None:
        return value
    store = _active_store()
    return await store.get(name) if store is not None else None


async def get_many(*names: str, source: Any = None) -> dict[str, str | None]:
    """``get`` for several names at once, with one store read for whatever
    ``.env`` does not set: a provider's key and its settings together."""
    found = {name: _from_env(name, source) for name in names}
    missing = [name for name, value in found.items() if value is None]
    store = _active_store()
    if missing and store is not None:
        found |= await store.get_many(missing)
    return found


def _declared(name: str) -> Secret:
    entry = next((s for s in declared() if s.name == name), None)
    if entry is None:
        raise UnknownSecretError(f"{name} is not a declared secret.")
    return entry


def _writable_store(name: str) -> tuple[Secret, SecretStore]:
    """The declaration and the store a write to ``name`` goes to, or the
    reason it cannot."""
    entry = _declared(name)
    if _from_env(name) is not None:
        raise SecretsReadOnlyError(
            f"{name} is set in .env, which wins: change it there."
        )
    if not entry.live:
        raise SecretsReadOnlyError(
            f"{name} is read from .env by the code that uses it: set it there."
        )
    store = _active_store()
    if store is None:
        raise SecretsReadOnlyError(
            f"No writable backend: set {name} in .env, or add the secrets component."
        )
    if not store.writable:
        raise SecretsReadOnlyError(
            f"{name} is managed in {store.name}: change it there."
        )
    return entry, store


async def put(name: str, value: str, actor: str) -> Verdict | None:
    """Store ``value`` for a declared ``name``, or refuse with the reason.
    A value the provider refuses raises ``SecretRejectedError`` and is not
    stored; one it could not be asked about is stored unverified. Returns
    the check's verdict, None where the name has no check."""
    entry, store = _writable_store(name)
    if entry.parse is not None:
        value = entry.parse(value)
    verdict = await _verify(entry, value)
    if verdict is not None and verdict.result == REJECTED:
        raise SecretRejectedError(verdict.message)
    await store.put(name, value, _hint(entry, value), actor)
    return verdict


async def test(name: str) -> Verdict:
    """Check the value in effect for ``name``, wherever it is set."""
    entry = _declared(name)
    value = await get(name)
    if value is None:
        return Verdict(UNVERIFIED, f"{name} is not set.")
    return await _verify(entry, value) or Verdict(
        UNVERIFIED, f"There is no check for {name}."
    )


async def choices(name: str) -> list[tuple[str, str]]:
    """What the provider offers for ``name`` as (value, label); empty when
    it has no list or cannot be asked, so typing the value still works."""
    entry = _declared(name)
    if entry.choices is None:
        return []
    try:
        return await entry.choices()
    except (SecretUncheckedError, SecretRejectedError) as exc:
        logger.info("No choices for secret", name=name, reason=str(exc))
        return []


async def _verify(entry: Secret, value: str) -> Verdict | None:
    if entry.verify is None:
        return None
    try:
        await entry.verify(value)
    except SecretRejectedError as exc:
        return Verdict(REJECTED, f"{entry.name} was refused: {exc}")
    except SecretUncheckedError as exc:
        return Verdict(UNVERIFIED, f"{entry.name} could not be checked: {exc}")
    return Verdict(VERIFIED, f"{entry.name} works.")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=VERIFY_TIMEOUT)


def _accepted(response: httpx.Response) -> bool:
    return response.is_success


async def probe(
    url: str,
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    rejected: tuple[int, ...] = (401,),
    passes: Callable[[httpx.Response], bool] = _accepted,
    json: dict[str, Any] | None = None,
) -> None:
    """A ``verify`` in one call: an authenticated GET to a cheap endpoint,
    or a POST of ``json`` for a provider that takes its keys in the body.
    ``passes`` says the credential works; a ``rejected`` status says it does
    not. The provider's body is never repeated: some echo part of the key."""
    host = urlsplit(url).hostname or url
    try:
        async with _client() as client:
            if json is None:
                response = await client.get(url, headers=headers, auth=auth)
            else:
                response = await client.post(url, headers=headers, json=json)
    except httpx.HTTPError as exc:
        logger.warning(
            "Secret check could not reach provider", host=host, error=type(exc).__name__
        )
        raise SecretUncheckedError(f"could not reach {host}.") from None
    if passes(response):
        return
    if response.status_code in rejected:
        raise SecretRejectedError(f"{host} refused it ({response.status_code}).")
    raise SecretUncheckedError(f"{host} answered {response.status_code}.")


async def delete(name: str, actor: str) -> None:
    """Remove the stored value for ``name``, or refuse with the reason."""
    _, store = _writable_store(name)
    await store.delete(name, actor)


def _hint(entry: Secret, value: str) -> str | None:
    if not entry.secret:
        return value
    return value[-4:] if len(value) >= HINT_MIN_LENGTH else None


def _row(
    entry: Secret,
    source: str | None = None,
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
        needed=entry.is_needed(),
        verifiable=entry.verify is not None,
        live=entry.live,
        choosable=entry.choices is not None,
        setting=entry.setting,
        default=entry.default,
    )


async def status_of(name: str) -> SecretStatus | None:
    """One declared name's status, a credential's or a setting's."""
    rows = await status(setting=is_setting(name))
    return next((row for row in rows if row.name == name), None)


async def status(setting: bool = False) -> list[SecretStatus]:
    """Every declared secret (or, with ``setting``, every saved-setting
    field): where it is set, its hint, when and by whom."""
    store = _active_store()
    stored = await store.stored() if store is not None else {}
    rows = []
    for entry in declared():
        if entry.setting != setting:
            continue
        if (value := _from_env(entry.name)) is not None:
            rows.append(_row(entry, ENV, _hint(entry, value)))
        elif store is not None and (kept := stored.get(entry.name)) is not None:
            rows.append(_row(entry, store.name, kept.hint, kept))
        else:
            rows.append(_row(entry))
    return rows
