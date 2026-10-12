"""The data side of a deploy backup: SQLite, the object store, an off-box copy.

``aegis deploy`` (before it deploys) and ``aegis deploy-backup`` copy the
deploy directory into ``backups/<timestamp>/files``: the code and the
server's ``.env``. The data needs more than a file copy, so it lands
beside it:

- ``data/``: the SQLite database, through SQLite's online backup API in the
  webserver container. A byte copy of a live WAL database misses every
  commit not yet checkpointed. With a snapshot, ``files/`` skips ``data/``,
  so a rollback's ``rsync --delete`` clears the live database and its
  ``-wal`` before the snapshot goes in.
- ``storage.tar.gz``: the object store, a named volume outside the
  directory.

Off-box, opt-in: when the server has ``offsite_env(deploy_path)``, each
backup is pushed with restic (client-side encrypted) to the repository it
names, everything but ``files/``. The ``.env``, keys and the restic
password never reach the bucket.

Every function takes ``run``, the caller's remote runner, so this module
holds the commands and ``deploy.py`` keeps the SSH.
"""

import re
import shlex
import subprocess
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

import typer

from ..cli import brand
from ..constants import AnswerKeys, StorageBackends
from ..i18n import t

Run = Callable[[str], subprocess.CompletedProcess[str]]

BACKUP_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}$")
STORAGE_ROOT = "/data/storage"
STORAGE_ARCHIVE = "storage.tar.gz"

# Runs in the webserver container and writes a tar of the snapshot to
# stdout, named relative to the ``./data`` bind mount. stdout is moved to
# stderr before the app is imported, so nothing it logs lands in the tar.
_SQLITE_SNAPSHOT = """\
import os, sqlite3, tarfile, tempfile
from pathlib import Path
out = os.fdopen(os.dup(1), "wb")
os.dup2(2, 1)
from app.core.db import DATABASE_PATH
src = Path(DATABASE_PATH).resolve()
with tempfile.TemporaryDirectory() as tmp:
    snap = Path(tmp, src.name)
    live, copy = sqlite3.connect(f"file:{src}?mode=ro", uri=True), sqlite3.connect(snap)
    live.backup(copy)
    copy.close()
    live.close()
    with tarfile.open(fileobj=out, mode="w|") as tar:
        tar.add(snap, arcname=str(src.relative_to(Path("data").resolve())))
out.close()
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


def offsite_env(deploy_path: str) -> str:
    """The server file that turns the off-box copy on.

    Outside the deploy directory: a deploy rsyncs into it with ``--delete``.
    """
    return f"/etc/aegis/{PurePosixPath(deploy_path).name}.restic.env"


def snapshot_sqlite(run: Run, compose_prefix: str, backup_dir: str) -> bool:
    """Snapshot the live database into ``<backup>/data``. False on failure,
    with nothing partial left behind."""
    typer.echo(t("deploy.backup_sqlite"))
    target = shlex.quote(f"{backup_dir}/data")
    result = run(
        f"set -o pipefail; mkdir -p {target} && {compose_prefix} exec -T webserver"
        f" python -c {shlex.quote(_SQLITE_SNAPSHOT)} | tar -xf - -C {target}"
        f" || {{ rm -rf {target}; false; }}"
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


def push_offsite(run: Run, deploy_path: str, backup_dir: str, timestamp: str) -> None:
    """Copy the backup, minus ``files/``, off the box when the server is
    configured for it; the repository is initialised on first use.

    ponytail: runs only when a backup does (each deploy, each
    ``deploy-backup``); schedule ``aegis deploy-backup`` for a cadence.
    """
    env = shlex.quote(offsite_env(deploy_path))
    if run(f"test -f {env}").returncode != 0:
        return
    typer.echo(t("deploy.backup_offsite"))
    backup = shlex.quote(backup_dir)
    files = shlex.quote(f"{backup_dir}/files")
    result = run(
        f"set -a && . {env} && set +a"
        " && { restic cat config >/dev/null 2>&1 || restic init; }"
        f" && restic backup --tag {shlex.quote(timestamp)} --exclude {files} {backup}"
    )
    if result.returncode != 0:
        brand.warn(t("deploy.backup_offsite_failed", error=result.stderr.strip()))


def restore_data(
    run: Run, compose_prefix: str, deploy_path: str, backup_dir: str
) -> bool:
    """Put back what ``snapshot_sqlite`` and ``archive_storage`` captured.

    The stack must be down; a backup without them restores nothing here.
    """
    data = shlex.quote(f"{backup_dir}/data")
    live = shlex.quote(f"{deploy_path}/data")
    archive = shlex.quote(f"{backup_dir}/{STORAGE_ARCHIVE}")
    unpack = shlex.quote(
        f"find {STORAGE_ROOT} -mindepth 1 -delete && tar -xzf - -C {STORAGE_ROOT}"
    )
    result = run(
        f"{{ [ ! -d {data} ] || {{ mkdir -p {live} && cp -a {data}/. {live}/; }}; }}"
        f" && {{ [ ! -f {archive} ] || {{ {compose_prefix} run --rm --no-deps -T"
        f" --entrypoint sh webserver -c {unpack} < {archive}; }}; }}"
    )
    if result.returncode != 0:
        brand.error(t("deploy.rollback_data_failed", error=result.stderr), err=True)
    return result.returncode == 0


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
