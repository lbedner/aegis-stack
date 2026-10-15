"""``aegis deploy-upload-db``: this machine's SQLite database onto the server.

A deploy ships the code and skips ``data/``, so a new server starts empty.
This brings the database you have been using. Both ends go through the
project's own webserver container and its ``DATABASE_PATH``, so it works
wherever the project keeps the file (a bind mount or a named volume):

- here, SQLite's online backup API in the running stack, a consistent
  copy while it runs (a byte copy of a live WAL database is not);
- there, after a backup and with the stack down, the copy checked (a
  whole SQLite database that passes ``integrity_check``) before it
  replaces the server's, whose ``-wal``/``-shm`` go with it.

The server's ``.env`` carries this machine's ``ENCRYPTION_KEY`` (from
``.env.deploy``), so encrypted columns still decrypt there.
"""

import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import typer

from ..cli import brand
from ..i18n import lazy_t, t
from .deploy import (
    _compose_prefix,
    _create_backup,
    _get_project_root,
    _load_deploy_config,
    _project_answers,
    _run_remote_capture,
)
from .deploy_backup import is_sqlite

# Runs in the local webserver container and writes the snapshot's bytes
# to stdout. stdout is moved to stderr before the app is imported, so
# nothing it logs lands in the copy.
_SNAPSHOT = """\
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

# Runs in a one-off server webserver container, the stack down: stdin
# beside the database, checked, then in its place. An empty file is a
# valid empty database to SQLite, hence the header.
_RESTORE = """\
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


def _snapshot(root: Path, out: Path) -> bool:
    """This machine's database into ``out``, from the running stack."""
    with out.open("wb") as f:
        done = subprocess.run(
            ["docker", "compose", "exec", "-T", "webserver"]
            + ["python", "-c", _SNAPSHOT],
            cwd=root,
            stdout=f,
            stderr=subprocess.PIPE,
        )
    return done.returncode == 0 and out.stat().st_size > 0


def refuse_unless_sqlite(root: Path) -> None:
    if not is_sqlite(_project_answers(root)):
        brand.error(t("deploy.upload_not_sqlite"), err=True)
        raise typer.Exit(1)


def upload_db(root: Path, server: dict[str, Any]) -> None:
    """Replace the server's database (``server``, deploy.yml's) with this
    machine's: nothing on the server is touched until the local copy exists
    and the server is backed up; a refused copy leaves the server's in
    place."""
    host, user, deploy_path = server["host"], server["user"], server["path"]
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp, "app.db")
        typer.echo(t("deploy.upload_snapshot"))
        if not _snapshot(root, snapshot):
            brand.error(t("deploy.upload_no_snapshot"), err=True)
            raise typer.Exit(1)
        if _create_backup(host, user, deploy_path, sqlite=True) is None:
            brand.error(t("deploy.upload_backup_failed"), err=True)
            raise typer.Exit(1)
        prefix = _compose_prefix(deploy_path)
        typer.echo(t("deploy.upload_restoring"))
        _run_remote_capture(host, user, f"{prefix} down")
        restored = _run_remote_capture(
            host,
            user,
            f"{prefix} run --rm --no-deps -T --entrypoint python webserver"
            f" -c {shlex.quote(_RESTORE)}",
            snapshot,
        )
        started = _run_remote_capture(host, user, f"{prefix} up -d")
    if restored.returncode != 0:
        brand.error(t("deploy.upload_refused", error=restored.stderr.strip()), err=True)
        raise typer.Exit(1)
    if started.returncode != 0:
        brand.error(t("deploy.upload_start_failed"), err=True)
        raise typer.Exit(1)
    brand.success(t("deploy.upload_done", host=host))


def deploy_upload_db_command(
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help=lazy_t("common.help_yes")),
) -> None:
    """
    Copy this machine's database to the server, replacing the server's.

    SQLite only. Snapshots the database of the running local stack, backs
    the server up, then puts the copy in place and restarts the server.
    """
    root = _get_project_root(project_path)
    refuse_unless_sqlite(root)
    config = _load_deploy_config(project_path)
    if not config:
        brand.error(t("deploy.no_config"), err=True)
        raise typer.Exit(1)
    server = config["server"]
    if not yes:
        typer.confirm(t("deploy.upload_confirm", host=server["host"]), abort=True)
    upload_db(root, server)
