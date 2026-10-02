"""The secrets component's store: write-only credentials, encrypted in the
database, live in every process.

``app.core.secrets`` finds this module the first time any process asks
(webserver, worker, scheduler) and calls ``install``, which sets the store
or says why it cannot. The rules (declared names only, ``.env`` wins, the
hint) are core's; this module keeps rows.

Reads go through the shared cache (``app.core.cache``; Redis when the
stack has it) holding the encrypted row, never a decrypted value: ``get``
decrypts at the moment of use. A write clears the entry, so the next read
in any process sees it; without Redis each process keeps its own copy and
catches up within ``CACHE_TTL``. The cache is reached directly rather than
as an endpoint dependency because worker and scheduler code reads secrets
too.
"""

from cryptography.fernet import InvalidToken
from sqlmodel import col, select

from app.core.audit import get_audit
from app.core.cache import get_cache
from app.core.config import settings
from app.core.db import get_async_session
from app.core.encryption import decrypt_secret, encrypt_secret
from app.core.secrets import SecretUnreadableError, StoredSecret, set_store
from app.core.time import utcnow

from .models import SecretRecord

CACHE_PREFIX = "secret:"
CACHE_TTL = 30
# Cached for a name with no row, so a status poll over keys nobody stored
# does not query the table each time. A write clears it like any entry.
ABSENT = ""
NO_KEY = (
    "ENCRYPTION_KEY is not set, so stored secrets cannot be read or written. "
    "Add one to .env (it must never change once keys are stored) and restart."
)


def _context(name: str) -> str:
    """Binds a ciphertext to its name: moved to another, it will not decrypt."""
    return f"secret:{name}"


def _decrypt(name: str, ciphertext: str) -> str:
    try:
        return decrypt_secret(ciphertext, context=_context(name))
    except InvalidToken:
        raise SecretUnreadableError(
            f"{name} will not decrypt: a different ENCRYPTION_KEY, or a "
            "value moved from another name. Set it again."
        ) from None


class DatabaseStore:
    """Rows in the ``secret`` table, read through the shared cache."""

    name = "database"
    writable = True

    async def get(self, name: str) -> str | None:
        return (await self.get_many([name]))[name]

    async def get_many(self, names: list[str]) -> dict[str, str | None]:
        """Cached rows first, then one query for the rest."""
        cache = get_cache()
        ciphertexts = {name: await cache.get(CACHE_PREFIX + name) for name in names}
        missing = [name for name, value in ciphertexts.items() if value is None]
        if missing:
            async with get_async_session() as db:
                rows = (
                    await db.exec(
                        select(SecretRecord).where(col(SecretRecord.name).in_(missing))
                    )
                ).all()
            stored = {row.name: row.ciphertext for row in rows}
            for name in missing:
                ciphertexts[name] = stored.get(name, ABSENT)
                await cache.set(CACHE_PREFIX + name, ciphertexts[name], CACHE_TTL)
        return {
            name: _decrypt(name, value) if value else None
            for name, value in ciphertexts.items()
        }

    async def put(self, name: str, value: str, hint: str | None, actor: str) -> None:
        ciphertext = encrypt_secret(value, context=_context(name))
        async with get_async_session() as db:
            row = await db.get(SecretRecord, name) or SecretRecord(
                name=name, ciphertext=ciphertext
            )
            row.ciphertext, row.hint = ciphertext, hint
            row.set_by, row.set_at = actor, utcnow()
            db.add(row)
            await db.commit()
        await get_cache().invalidate(CACHE_PREFIX + name)
        await get_audit().emit(
            "secrets.set", actor_email=actor, target_type="secret", detail=name
        )

    async def delete(self, name: str, actor: str) -> None:
        async with get_async_session() as db:
            row = await db.get(SecretRecord, name)
            if row is not None:
                await db.delete(row)
                await db.commit()
        await get_cache().invalidate(CACHE_PREFIX + name)
        await get_audit().emit(
            "secrets.deleted", actor_email=actor, target_type="secret", detail=name
        )

    async def stored(self) -> dict[str, StoredSecret]:
        """Every stored row's hint, setter and time: one query, no decrypt."""
        async with get_async_session() as db:
            rows = (await db.exec(select(SecretRecord))).all()
        return {
            row.name: StoredSecret(hint=row.hint, set_at=row.set_at, set_by=row.set_by)
            for row in rows
        }


def install() -> str | None:
    """Install the store, or return why not. No fallback to SECRET_KEY:
    rotating the session key would strand every stored secret."""
    if not getattr(settings, "ENCRYPTION_KEY", None):
        return NO_KEY
    set_store(DatabaseStore())
    return None
