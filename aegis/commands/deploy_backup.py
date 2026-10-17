"""The data side of a deploy backup: SQLite, the object store, an off-box copy.

``aegis deploy`` (before it deploys) and ``aegis deploy-backup`` copy the
deploy directory into ``backups/<timestamp>/files``: the code and the
server's ``.env``. The data needs more than a file copy, so it lands
beside it:

- ``database.db``: the SQLite database, through SQLite's online backup API
  in the webserver container, wherever ``DATABASE_PATH`` puts it. A byte
  copy of a live WAL database misses every commit not yet checkpointed.
  With a snapshot, ``files/`` skips ``data/``, so a rollback's
  ``rsync --delete`` never lays a live copy's ``-wal`` back down; the
  snapshot goes back in through the container, checked first.
- ``storage.tar.gz``: the object store, a named volume outside the
  directory.

These stay on the server, for rollbacks. The copy that leaves it is the
app's own nightly backup, sent by its off-site job
(``app.services.system.offsite``).

Every function takes ``run``, the caller's remote runner, so this module
holds the commands and ``deploy.py`` keeps the SSH.
"""

import re
import shlex
import subprocess
from collections.abc import Callable
from typing import Any

import typer

from ..cli import brand
from ..constants import AnswerKeys, StorageBackends
from ..i18n import t

Run = Callable[[str], subprocess.CompletedProcess[str]]

BACKUP_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}$")
STORAGE_ROOT = "/data/storage"
STORAGE_ARCHIVE = "storage.tar.gz"

DATABASE_FILE = "database.db"  # the SQLite snapshot, in a backup

# Runs in a webserver container (this machine's for an upload, the
# server's for a backup) and writes the snapshot's bytes to stdout, found
# through DATABASE_PATH wherever the project keeps it (a bind mount or a
# named volume). stdout is moved to stderr before the app is imported, so
# nothing it logs lands in the copy.
SNAPSHOT = """\
import os, shutil, sqlite3, tempfile
out = os.fdopen(os.dup(1), "wb")
os.dup2(2, 1)
from app.core.db import DATABASE_PATH
with tempfile.TemporaryDirectory() as tmp:
    snap = os.path.join(tmp, "snapshot.db")
    live = sqlite3.connect(f"file:{os.path.abspath(DATABASE_PATH)}?mode=ro", uri=True)
    copy = sqlite3.connect(snap)
    live.backup(copy)
    copy.close()
    live.close()
    with open(snap, "rb") as f:
        shutil.copyfileobj(f, out)
out.close()
"""

# Runs in a one-off server webserver container, the stack down (an
# upload, a rollback): stdin beside the database, checked, then in its place. An empty file is a
# valid empty database to SQLite, hence the header.
RESTORE = """\
import os, shutil, sqlite3, sys
from app.core.db import DATABASE_PATH
part = DATABASE_PATH + ".upload"
os.makedirs(os.path.dirname(os.path.abspath(DATABASE_PATH)), exist_ok=True)
try:
    with open(part, "wb") as f:
        shutil.copyfileobj(sys.stdin.buffer, f)
    with open(part, "rb") as f:
        if f.read(16) != b"SQLite format 3\\x00":
            sys.exit("the upload is not a SQLite database")
    db = sqlite3.connect(part)
    checked = db.execute("PRAGMA integrity_check").fetchone()[0]
    db.close()
    if checked != "ok":
        sys.exit(f"the upload failed its integrity check: {checked}")
    for extra in ("-wal", "-shm"):
        if os.path.exists(DATABASE_PATH + extra):
            os.remove(DATABASE_PATH + extra)
    os.replace(part, DATABASE_PATH)
finally:
    if os.path.exists(part):
        os.remove(part)
"""


def backup_config(config: dict[str, Any]) -> dict[str, Any]:
    """Backup settings from ``deploy.yml``, with defaults."""
    backup = config.get("backup", {}) or {}
    return {
        "keep_count": backup.get("keep_count", 5),
        "include_database": backup.get("include_database", True),
    }


def is_sqlite(answers: dict[str, Any]) -> bool:
    """The project keeps its database in SQLite (from its copier answers)."""
    return bool(answers.get(AnswerKeys.DATABASE)) and (
        answers.get(AnswerKeys.DATABASE_ENGINE) == StorageBackends.SQLITE
    )


def snapshot_sqlite(run: Run, compose_prefix: str, backup_dir: str) -> bool:
    """Snapshot the live database into ``<backup>/DATABASE_FILE``. False on
    failure, with nothing partial left behind."""
    typer.echo(t("deploy.backup_sqlite"))
    target = shlex.quote(f"{backup_dir}/{DATABASE_FILE}")
    # First into the backup: nothing has made its directory yet.
    result = run(
        f"mkdir -p {shlex.quote(backup_dir)} && {compose_prefix} exec -T webserver"
        f" python -c {shlex.quote(SNAPSHOT)} > {target} || {{ rm -f {target}; false; }}"
    )
    if result.returncode != 0:
        brand.warn(t("deploy.backup_sqlite_failed"))
    return result.returncode == 0


def archive_storage(run: Run, compose_prefix: str, backup_dir: str) -> None:
    """Tar the object store into the backup. A failure warns: the rest of
    the backup still stands."""
    archive = shlex.quote(f"{backup_dir}/{STORAGE_ARCHIVE}")
    result = run(
        f"{compose_prefix} exec -T webserver tar -czf - -C {STORAGE_ROOT} ."
        f" > {archive} || {{ rm -f {archive}; false; }}"
    )
    if result.returncode != 0:
        brand.warn(t("deploy.backup_storage_failed"))


def restore_data(
    run: Run, compose_prefix: str, deploy_path: str, backup_dir: str
) -> bool:
    """Put back what ``snapshot_sqlite`` and ``archive_storage`` captured.

    The stack must be down; a backup without them restores nothing here.
    A backup from before aegis-stack#1627 holds ``data/`` (a copy of the
    ``./data`` bind mount) instead of ``DATABASE_FILE``.
    """
    db = shlex.quote(f"{backup_dir}/{DATABASE_FILE}")
    data = shlex.quote(f"{backup_dir}/data")
    live = shlex.quote(f"{deploy_path}/data")
    archive = shlex.quote(f"{backup_dir}/{STORAGE_ARCHIVE}")
    unpack = shlex.quote(
        f"find {STORAGE_ROOT} -mindepth 1 -delete && tar -xzf - -C {STORAGE_ROOT}"
    )
    result = run(
        f"{{ [ ! -f {db} ] || {compose_prefix} run --rm --no-deps -T --entrypoint"
        f" python webserver -c {shlex.quote(RESTORE)} < {db}; }}"
        f" && {{ [ ! -d {data} ] || {{ mkdir -p {live} && cp -a {data}/. {live}/; }}; }}"
        f" && {{ [ ! -f {archive} ] || {{ {compose_prefix} run --rm --no-deps -T"
        f" --entrypoint sh webserver -c {unpack} < {archive}; }}; }}"
    )
    if result.returncode != 0:
        brand.error(t("deploy.rollback_data_failed", error=result.stderr), err=True)
    return result.returncode == 0


def list_backups(run: Run, deploy_path: str) -> list[dict[str, Any]]:
    """The server's backups, newest first: each one's name (its timestamp),
    size, and whether it holds the database (a SQLite snapshot, a Postgres
    dump, or an older backup's ``data/``). One remote call; none yet, an
    empty list."""
    root = shlex.quote(f"{deploy_path}/backups")
    held = f'-f "$b/{DATABASE_FILE}" -o -f "$b/db_backup.sql" -o -d "$b/data"'
    result = run(
        f"cd {root} 2>/dev/null || exit 0; for b in $(ls -1t); do"
        f' printf "%s\\t%s\\t%s\\n" "$b" "$(du -sh "$b" | cut -f1)"'
        f' "$(test {held} && echo y)"; done'
    )
    backups = []
    for line in result.stdout.splitlines():
        name, size, database = (line.split("\t") + ["", ""])[:3]
        if BACKUP_TIMESTAMP_RE.match(name):
            backups.append({"name": name, "size": size, "database": database == "y"})
    return backups


def prune_backups(run: Run, deploy_path: str, keep_count: int) -> None:
    """Remove old backups, keeping only the most recent N."""
    safe_path = shlex.quote(f"{deploy_path}/backups")
    result = run(f"ls -1t {safe_path} 2>/dev/null")
    if result.returncode != 0 or not result.stdout.strip():
        return

    backups = [b.strip() for b in result.stdout.strip().splitlines() if b.strip()]
    for old_backup in backups[keep_count:]:
        if not BACKUP_TIMESTAMP_RE.match(old_backup):
            continue  # skip unexpected directory names
        run(f"rm -rf {shlex.quote(f'{deploy_path}/backups/{old_backup}')}")
        typer.echo(t("deploy.backup_pruned", name=old_backup))
