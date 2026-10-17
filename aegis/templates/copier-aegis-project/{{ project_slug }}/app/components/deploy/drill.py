"""A restore drill's checks, run against a restored copy by the app's own
code (``deploy drill-check``; ``aegis deploy-restore-drill`` runs it in a
throwaway container pointed at what it restored).

Each check is ``{"name", "ok", "said"}``: the copy migrates to this code's
head (as a restore must, before anything reads it), the database file is
whole, every stored secret decrypts with this ``ENCRYPTION_KEY`` (the key
kept off the server is the right one), and every stored file a row names
is in the restored store. A copy that will not migrate is checked no
further: the rest would read tables it does not have.
"""

import asyncio
from pathlib import Path
import sqlite3
from typing import Any

from app.core.db import get_async_session
from app.core.storage import missing_objects

ALEMBIC_INI = Path("alembic/alembic.ini")


def _migrated(database: Path) -> dict[str, Any]:
    """The copy brought to this code's head, through the settings' database
    (the restored copy, in the drill's container)."""
    from alembic import command
    from alembic.config import Config

    try:
        command.upgrade(Config(str(ALEMBIC_INI)), "head")
    except Exception as exc:
        said = str(exc).strip().splitlines()[-1:] or [type(exc).__name__]
        return {"name": "migrations", "ok": False, "said": said[0][:300]}
    return {"name": "migrations", "ok": True, "said": "Brought to head"}


def _whole(database: Path) -> dict[str, Any]:
    try:
        db = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            found = db.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            db.close()
    except sqlite3.DatabaseError as exc:
        found = str(exc)
    return {"name": "database", "ok": found == "ok", "said": f"integrity: {found}"}


async def _secrets() -> dict[str, Any]:
    try:
        from app.components.secrets.store import DatabaseStore
    except ImportError:  # no secrets component: nothing stored to read
        return {"name": "secrets", "ok": True, "said": "No secrets store."}
    from app.core.secrets import SecretUnreadableError

    store = DatabaseStore()
    names = list(await store.stored())
    try:
        await store.get_many(names)
    except SecretUnreadableError as exc:  # names the first that will not
        return {"name": "secrets", "ok": False, "said": str(exc)}
    return {"name": "secrets", "ok": True, "said": f"{len(names)} read"}


async def _files() -> dict[str, Any]:
    async with get_async_session() as session:
        missing = await missing_objects(session)
    if missing:
        said = f"{len(missing)} stored file{'s' if len(missing) != 1 else ''} missing"
        return {"name": "files", "ok": False, "said": said, "missing": missing[:20]}
    return {"name": "files", "ok": True, "said": "Every stored file present"}


def read_alone() -> None:
    """The copy read on its own cache: a throwaway container has no Redis,
    and a cache shared with a running stack could answer with that stack's
    values instead of the copy's (``deploy drill-check`` calls this)."""
    import app.core.cache as shared

    shared.cache = shared.CacheService(redis_url=None)


async def drill_check(database: Path) -> list[dict[str, Any]]:
    """Each check against the restored ``database`` and the store the app
    is pointed at."""
    migrated = await asyncio.to_thread(_migrated, database)
    if not migrated["ok"]:
        return [migrated]
    return [
        migrated,
        await asyncio.to_thread(_whole, database),
        await _secrets(),
        await _files(),
    ]
