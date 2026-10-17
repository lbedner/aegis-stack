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

``aegis deploy-upload-storage``: the stored files the server's rows name
and its store lacks (the project's ``storage check``), from this
machine's store. The database upload ends with it, since rows name files
a database copy does not carry (aegis-stack#1679).
"""

import shlex
import subprocess
import tempfile
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import typer

from ..cli import brand
from ..i18n import lazy_t, t
from .deploy import (
    APP_CLI,
    _compose_prefix,
    _create_backup,
    _exec_command,
    _get_project_root,
    _project_answers,
    _require_deploy_config,
    _run_remote_capture,
    recorded,
)
from .deploy_backup import RESTORE, SNAPSHOT, STORAGE_ROOT, is_sqlite


def _local(root: Path, command: list[str], out: Path, stdin: bytes = b"") -> bool:
    """``command`` in this machine's running webserver, stdout into ``out``."""
    with out.open("wb") as f:
        done = subprocess.run(
            ["docker", "compose", "exec", "-T", "webserver", *command],
            cwd=root,
            input=stdin,
            stdout=f,
            stderr=subprocess.PIPE,
        )
    return done.returncode == 0


def _snapshot(root: Path, out: Path) -> bool:
    """This machine's database into ``out``, from the running stack."""
    return _local(root, ["python", "-c", SNAPSHOT], out) and out.stat().st_size > 0


# The project's own check: the keys its rows name and its store lacks.
STORAGE_CHECK = [*APP_CLI, "storage", "check"]
# Keys on stdin, this machine's store's copies out as a tarball; a key
# this store lacks too is left out, and the check after says so.
_PACK = (
    f'cd {STORAGE_ROOT} && while read -r k; do [ -f "$k" ] && echo "$k"; done'
    " | tar -czf - -T -"
)


def server_missing(remote: Callable[..., Any], deploy_path: str) -> list[str] | None:
    """The keys the server's rows name and its store lacks (its ``storage
    check``, through ``remote``); None when the server cannot say (a
    project from before it)."""
    done = remote(_exec_command(deploy_path, "webserver", STORAGE_CHECK))
    if done.returncode not in (0, 1):
        return None
    # stdout is the keys alone; what a person reads goes to stderr.
    return done.stdout.split()


def _pack(root: Path, keys: list[str], out: Path) -> bool:
    """These objects from this machine's store into ``out``."""
    return _local(root, ["sh", "-c", _PACK], out, "\n".join(keys).encode() + b"\n")


def upload_storage(root: Path, server: dict[str, Any]) -> None:
    """Bring the stored files the server's rows name and its store lacks.

    Add only: a key is its file's hash, so nothing the server holds is
    replaced. ponytail: into the server's filesystem store; a server on a
    bucket fills it with its own copy.
    """
    with recorded(root, server, "upload-storage") as said:
        host, deploy_path = server["host"], server["path"]
        remote = partial(_run_remote_capture, host, server["user"])
        missing = server_missing(remote, deploy_path)
        brought = len(missing or [])
        if missing:
            typer.echo(t("deploy.storage_copying", count=len(missing)))
            with tempfile.TemporaryDirectory() as tmp:
                archive = Path(tmp, "storage.tar.gz")
                if not _pack(root, missing, archive):
                    brand.error(t("deploy.storage_no_pack"), err=True)
                    raise typer.Exit(1)
                unpack = ["tar", "-xzf", "-", "-C", STORAGE_ROOT]
                unpacked = remote(
                    _exec_command(deploy_path, "webserver", unpack), archive
                )
            if unpacked.returncode != 0:
                brand.error(
                    t("deploy.storage_refused", error=unpacked.stderr.strip()), err=True
                )
                raise typer.Exit(1)
            missing = server_missing(remote, deploy_path)
        if missing is None:
            brand.warn(t("deploy.storage_cannot_check"))
            said["summary"] = "The server could not say which stored files it lacks"
            raise typer.Exit(1)
        if missing:
            said["summary"] = f"{len(missing)} stored files still missing"
            # The count, never the keys: the app's ``storage check`` reads
            # an event's JSON too, and would name them missing forever.
            said["detail"] = {"brought": brought, "missing": len(missing)}
            brand.error(
                t(
                    "deploy.storage_still_missing",
                    count=len(missing),
                    keys="\n".join(missing),
                ),
                err=True,
            )
            raise typer.Exit(1)
        said["summary"] = (
            f"Brought {brought} stored files"
            if brought
            else "Every stored file was there"
        )
        said["detail"] = {"brought": brought}
        brand.success(t("deploy.storage_done", host=host))


def refuse_unless_sqlite(root: Path, why: str = "deploy.upload_not_sqlite") -> None:
    """Stop unless the project's database is SQLite, saying ``why``."""
    if not is_sqlite(_project_answers(root)):
        brand.error(t(why), err=True)
        raise typer.Exit(1)


def upload_db(root: Path, server: dict[str, Any]) -> None:
    """Replace the server's database (``server``, deploy.yml's) with this
    machine's: nothing on the server is touched until the local copy exists
    and the server is backed up; a refused copy leaves the server's in
    place."""
    with recorded(root, server, "upload-db") as said:
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
                f" -c {shlex.quote(RESTORE)}",
                snapshot,
            )
            started = _run_remote_capture(host, user, f"{prefix} up -d")
        if restored.returncode != 0:
            brand.error(
                t("deploy.upload_refused", error=restored.stderr.strip()), err=True
            )
            raise typer.Exit(1)
        if started.returncode != 0:
            brand.error(t("deploy.upload_start_failed"), err=True)
            raise typer.Exit(1)
        said["summary"] = "Replaced the server's database with this machine's"
        brand.success(t("deploy.upload_done", host=host))
    upload_storage(root, server)


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
    config = _require_deploy_config(project_path)
    server = config["server"]
    if not yes:
        typer.confirm(t("deploy.upload_confirm", host=server["host"]), abort=True)
    upload_db(root, server)


def deploy_upload_storage_command(
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
) -> None:
    """
    Copy the stored files the server's database names and its store lacks.

    From this machine's running stack; adds only, so nothing on the server
    is replaced. Fails naming any file neither machine has.
    """
    config = _require_deploy_config(project_path)
    upload_storage(_get_project_root(project_path), config["server"])
