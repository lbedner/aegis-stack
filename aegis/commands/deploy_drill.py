"""``aegis deploy-restore-drill``: does the newest off-site copy restore?

The copy the server's nightly job sent (``OFFSITE_BACKUP_*`` in the
shipped env file, ``.env.deploy`` over ``.env``) is restored into a
scratch directory on this machine by restic's own image, then checked by
the project's own code in a throwaway container from its webserver image
(``deploy drill-check``): the database whole, every stored secret readable
with the ``ENCRYPTION_KEY`` kept off the server, every stored file present.
Production is never touched but for the drill's record (``recorded``),
and the scratch directory is emptied however the drill ends.
"""

import json
import os
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any

import typer

from ..cli import brand
from ..core.deploy_protocol import step
from ..core.template_cleanup import deploy_env_file, env_value
from ..i18n import lazy_t, t
from .deploy import _get_project_root, _require_deploy_config, recorded

RESTIC_IMAGE = "restic/restic:0.18.0"
# Each setting the drill reads, and the name restic and its S3 client read
# it by; ENCRYPTION_KEY goes to the app's container.
RESTIC_ENV = {
    "OFFSITE_BACKUP_REPOSITORY": "RESTIC_REPOSITORY",
    "OFFSITE_BACKUP_PASSWORD": "RESTIC_PASSWORD",
    "OFFSITE_BACKUP_ACCESS_KEY": "AWS_ACCESS_KEY_ID",
    "OFFSITE_BACKUP_SECRET_KEY": "AWS_SECRET_ACCESS_KEY",
}
KEY = "ENCRYPTION_KEY"
SCRATCH = "/drill"  # where the scratch directory is mounted in each container
STEPS = ["restore", "check", "record"]


class DrillError(RuntimeError):
    """Why the drill could not get as far as its checks."""


def _settings(root: Path) -> dict[str, str]:
    """The off-site settings and ``ENCRYPTION_KEY``, as a deploy ships them."""
    shipped = deploy_env_file(root)
    found = {
        name: env_value(shipped, name) if shipped else None
        for name in (*RESTIC_ENV, KEY)
    }
    if missing := [name for name, value in found.items() if not value]:
        where = shipped.name if shipped else ".env.deploy"
        raise DrillError(f"{', '.join(missing)} not set in {where}")
    return {name: str(value) for name, value in found.items()}


def _docker(
    args: list[str], env: dict[str, str] | None = None, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """``docker args``; values in ``env`` reach a container through ``-e
    NAME`` (never on the command line, where ``ps`` shows them)."""
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=os.environ | (env or {}),
    )


def _passing(env: dict[str, str]) -> list[str]:
    return [arg for name in env for arg in ("-e", name)]


def _restic(scratch: str, env: dict[str, str], *args: str) -> str:
    done = _docker(
        [
            "run",
            "--rm",
            "-v",
            f"{scratch}:{SCRATCH}",
            *_passing(env),
            RESTIC_IMAGE,
            *args,
        ],
        env,
    )
    if done.returncode:
        raise DrillError(f"restic {args[0]} failed: {done.stderr.strip()}")
    return done.stdout


def _app_image(root: Path) -> str:
    """The project's webserver image, as its running stack has it."""
    done = _docker(["compose", "images", "webserver", "--format", "json"], cwd=root)
    found = json.loads(done.stdout or "[]") if done.returncode == 0 else []
    if not found:
        raise DrillError(t("deploy.drill_no_image"))
    return f"{found[0]['Repository']}:{found[0]['Tag']}"


def _unpack(scratch: Path) -> Path:
    """The restored database; the documents archive beside it unpacked
    into ``storage`` (an empty one when the copy has none)."""
    database = next(scratch.rglob("database_backup_*.db"), None)
    if database is None:
        raise DrillError("The copy holds no database snapshot")
    if (archive := next(scratch.rglob("storage_backup_*.tar"), None)) is not None:
        with tarfile.open(archive) as tar:  # holds ``storage/...``
            tar.extractall(scratch, filter="data")
    (scratch / "storage").mkdir(exist_ok=True)
    return database


def _check(
    root: Path, image: str, scratch: Path, database: Path, key: str
) -> list[dict[str, Any]]:
    """The app's own checks (``deploy drill-check``) against the restored
    copy, in a throwaway container: its database and store are the copy's,
    its code and migrations this checkout's (as the dev stack mounts them),
    not what the image last baked in."""
    inside = f"{SCRATCH}/{database.relative_to(scratch)}"
    env = {
        KEY: key,
        "DATABASE_URL": f"sqlite:///{inside}",
        "STORAGE_ROOT": f"{SCRATCH}/storage",
    }
    done = _docker(
        [
            "run",
            "--rm",
            "-v",
            f"{scratch}:{SCRATCH}",
            "-v",
            f"{root / 'app'}:/code/app:ro",
            "-v",
            f"{root / 'alembic'}:/code/alembic:ro",
            *_passing(env),
            "--entrypoint",
            "python",
            image,
            "-m",
            "app.cli.main",
            "deploy",
            "drill-check",
            "--database",
            inside,
        ],
        env,
    )
    lines = done.stdout.strip().splitlines()
    if done.returncode not in (0, 1) or not lines:
        why = (done.stderr.strip().splitlines() or ["no output"])[-1]
        raise DrillError(f"The checks did not run: {why[:300]}")
    return json.loads(lines[-1])


def _empty(scratch: str) -> None:
    """What the containers wrote, removed by one: they write as root."""
    _docker(
        [
            "run",
            "--rm",
            "-v",
            f"{scratch}:{SCRATCH}",
            "--entrypoint",
            "sh",
            RESTIC_IMAGE,
            "-c",
            f"rm -rf {SCRATCH}/*",
        ]
    )


def restore_drill(root: Path, server: dict[str, Any]) -> None:
    """Restore the newest off-site copy and check it; recorded on the
    server as a ``restore-drill`` event, passed or which check failed."""
    with recorded(root, server, "restore-drill") as said:
        began = time.monotonic()
        try:
            values = _settings(root)
            restic = {RESTIC_ENV[name]: values[name] for name in RESTIC_ENV}
            image = _app_image(root)
            step(STEPS, "restore")
            typer.echo(t("deploy.drill_restoring"))
            with tempfile.TemporaryDirectory() as scratch:
                try:
                    snapshot = json.loads(
                        _restic(scratch, restic, "snapshots", "latest", "--json")
                    )[0]
                    _restic(scratch, restic, "restore", "latest", "--target", SCRATCH)
                    database = _unpack(Path(scratch))
                    step(STEPS, "check")
                    typer.echo(t("deploy.drill_checking"))
                    checks = _check(root, image, Path(scratch), database, values[KEY])
                finally:
                    _empty(scratch)
        except DrillError as exc:
            said["summary"] = str(exc)
            brand.error(str(exc), err=True)
            raise typer.Exit(1) from None
        step(STEPS, "record")
        failed = [c for c in checks if not c["ok"]]
        copy = f"{snapshot['short_id']} ({snapshot['time'][:16].replace('T', ' ')})"
        said["detail"] = {
            "snapshot": snapshot["short_id"],
            "taken": snapshot["time"],
            "checks": checks,
            "seconds": round(time.monotonic() - began),
        }
        said["summary"] = (
            f"Restored {copy}: "
            + "; ".join(f"{c['name']}: {c['said']}" for c in failed)
            if failed
            else f"Restored {copy}: {len(checks)} checks passed"
        )
        for c in checks:
            mark = brand.success if c["ok"] else brand.warn
            mark(f"{c['name']}: {c['said']}")
        if failed:
            raise typer.Exit(1)
    brand.success(t("deploy.drill_passed"))


def deploy_restore_drill_command(
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
) -> None:
    """
    Restore the newest off-site copy on this machine and check it.

    Nothing on the server changes; the drill is recorded there.
    """
    config = _require_deploy_config(project_path)
    restore_drill(_get_project_root(project_path), config["server"])
