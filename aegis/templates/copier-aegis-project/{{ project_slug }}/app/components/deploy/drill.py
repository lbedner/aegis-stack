"""A restore drill's checks, run against a restored copy by the app's own
code (``deploy drill-check``; ``aegis deploy-restore-drill`` runs it in a
throwaway container over what restic restored).

First the copy is laid out where the settings point (the container points
``DATABASE_URL`` and ``STORAGE_ROOT`` into its scratch directory): the
newest database snapshot the nightly backup took, and its documents
archive unpacked, found by the backup job's own names. Then each check is
``{"name", "ok", "said"}``: the file is whole, the app's own startup
brings it up (whatever a restored server runs at boot: its migrations, or
creating its tables), every stored secret decrypts with this
``ENCRYPTION_KEY`` (the key kept off the server is the right one), and
every stored file a row names is in the restored store. A copy that is
missing, damaged, or will not start is checked no further: the rest would
read what it does not have.
"""

import asyncio
from pathlib import Path
import shutil
import sqlite3
import tarfile
from typing import Any

from app.core import db
from app.core.config import settings
from app.core.db import get_async_session
from app.core.storage import missing_objects


def _laid_out(restored: Path) -> dict[str, Any]:
    """The newest snapshot under ``restored`` copied to the settings'
    database, and its documents archive unpacked into the settings' store.

    ``DATABASE_PATH`` exists only on SQLite, the one engine a drill
    restores (aegis refuses the rest), and the backup's names only with
    the scheduled backup: both read here, not on import, so a project
    without them still loads its ``deploy`` commands.
    """
    from app.services.system import backup

    # restic restores the server's absolute paths under ``restored``; the
    # stamp in a name orders them.
    pattern = backup.BACKUP_FILE_PATTERNS[0]
    found = sorted(restored.rglob(pattern), key=lambda p: p.name, reverse=True)
    if not found:
        return {"name": "copy", "ok": False, "said": "No database snapshot in it"}
    snapshot = found[0]
    shutil.copyfile(snapshot, db.DATABASE_PATH)
    stamp = snapshot.name.removeprefix(backup.BACKUP_FILE_PREFIX).removesuffix(
        backup.BACKUP_FILE_SUFFIX
    )
    archive = snapshot.with_name(
        f"{backup.STORAGE_BACKUP_PREFIX}{stamp}{backup.STORAGE_BACKUP_SUFFIX}"
    )
    store = Path(settings.STORAGE_ROOT)
    if archive.exists():  # holds ``storage/...`` (backup._snapshot_storage)
        with tarfile.open(archive) as tar:
            tar.extractall(archive.parent, filter="data")
        if (unpacked := archive.parent / "storage") != store:
            shutil.move(unpacked, store)
    store.mkdir(parents=True, exist_ok=True)
    said = f"{snapshot.name}{', with its documents' if archive.exists() else ''}"
    return {"name": "copy", "ok": True, "said": said}


def _whole() -> dict[str, Any]:
    try:
        copy = sqlite3.connect(f"file:{db.DATABASE_PATH}?mode=ro", uri=True)
        try:
            found = copy.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            copy.close()
    except sqlite3.DatabaseError as exc:
        found = str(exc)
    return {"name": "database", "ok": found == "ok", "said": f"integrity: {found}"}


async def _started() -> dict[str, Any]:
    """The app's own startup on the copy, as a restored server boots."""
    from app.components.backend.startup.database_init import startup_database_init

    try:
        await startup_database_init()
    except Exception as exc:
        said = str(exc).strip().splitlines()[-1:] or [type(exc).__name__]
        return {"name": "startup", "ok": False, "said": said[0][:300]}
    return {"name": "startup", "ok": True, "said": "Started as the app boots"}


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
        return {"name": "files", "ok": False, "said": said}
    return {"name": "files", "ok": True, "said": "Every stored file present"}


def read_alone() -> None:
    """The copy read on its own cache: a throwaway container has no Redis,
    and a cache shared with a running stack could answer with that stack's
    values instead of the copy's (``deploy drill-check`` calls this)."""
    import app.core.cache as shared

    shared.cache = shared.CacheService(redis_url=None)


async def drill_check(restored: Path) -> list[dict[str, Any]]:
    """The copy restic ``restored`` laid out, then each check against it,
    up to the first that leaves nothing for the rest to read."""
    checks = [await asyncio.to_thread(_laid_out, restored)]
    if checks[-1]["ok"]:
        checks.append(await asyncio.to_thread(_whole))
    if checks[-1]["ok"]:
        checks.append(await _started())
    if checks[-1]["ok"]:
        checks += [await _secrets(), await _files()]
    return checks
