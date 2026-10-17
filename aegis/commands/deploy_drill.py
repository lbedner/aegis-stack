"""``aegis deploy-restore-drill``: does the newest off-site copy restore?

The copy the server's nightly job sent (``OFFSITE_BACKUP_*`` in the
shipped env file, ``.env.deploy`` over ``.env``) is restored into a
scratch directory on this machine by restic's own image, then laid out and
checked by the project's own code in a throwaway container from its
webserver image (``deploy drill-check``, which knows its backup's names):
the database whole, the app starting on it, every stored secret readable
with the ``ENCRYPTION_KEY`` kept off the server, every stored file present.
Production is never touched but for the drill's record (``recorded``),
and the scratch directory is emptied however the drill ends.
"""

import json
import tempfile
import time
from pathlib import Path
from typing import Any

import typer

from ..cli import brand
from ..core.deploy_protocol import protocol, step
from ..core.footprint import DockerError, runner
from ..core.template_cleanup import deploy_env_file, env_value
from ..i18n import lazy_t, t
from .deploy import (
    APP_CLI,
    _get_project_root,
    _require_deploy_config,
    last_json,
    recorded,
)
from .deploy_upload import refuse_unless_sqlite

RESTIC_IMAGE = "restic/restic:0.18.0"
# The off-site settings, each as restic reads it (the app's job sends with
# the same); ENCRYPTION_KEY goes to the app's container.
RESTIC_ENV = protocol.RESTIC_ENV
KEY = "ENCRYPTION_KEY"
SCRATCH = "/drill"  # where the scratch directory is mounted in each container
STEPS = list(protocol.DRILL_STEPS)
# Restoring and checking a copy take as long as it is large.
SECONDS = 1800


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


def _passing(env: dict[str, str]) -> list[str]:
    """Each of ``env`` into a container by name (``runner`` holds them)."""
    return [arg for name in env for arg in ("-e", name)]


def _restic(scratch: str, env: dict[str, str], *args: str) -> str:
    mount = ["-v", f"{scratch}:{SCRATCH}", *_passing(env)]
    try:
        return runner(Path(scratch), env, SECONDS)(
            "run", "--rm", *mount, RESTIC_IMAGE, *args
        )
    except DockerError as exc:
        raise DrillError(f"restic {args[0]} failed: {exc}") from None


def _app_image(root: Path) -> str:
    """The project's webserver image, as its running stack has it."""
    try:
        out = runner(root)("compose", "images", "webserver", "--format", "json")
        found = json.loads(out or "[]")
    except (DockerError, ValueError):
        found = []
    if not found:
        raise DrillError(t("deploy.drill_no_image"))
    return f"{found[0]['Repository']}:{found[0]['Tag']}"


def _check(root: Path, image: str, scratch: Path, key: str) -> list[dict[str, Any]]:
    """The app's own checks (``deploy drill-check``) on what restic restored,
    in a throwaway container: it lays the copy out where its database and
    store point, in the scratch directory; its code and migrations are this
    checkout's (as the dev stack mounts them), not what the image baked in."""
    env = {
        KEY: key,
        "DATABASE_URL": f"sqlite:///{SCRATCH}/copy.db",
        "STORAGE_ROOT": f"{SCRATCH}/store",
    }
    mounts = [
        *("-v", f"{scratch}:{SCRATCH}"),
        *("-v", f"{root / 'app'}:/code/app:ro"),
        *("-v", f"{root / 'alembic'}:/code/alembic:ro"),
    ]
    python, *module = APP_CLI
    try:
        out = runner(root, env, SECONDS)(
            "run",
            "--rm",
            *mounts,
            *_passing(env),
            "--entrypoint",
            python,
            image,
            *module,
            "deploy",
            "drill-check",
            SCRATCH,
        )
    except DockerError as exc:
        why = (str(exc).splitlines() or ["no output"])[-1]
        raise DrillError(f"The checks did not run: {why[:300]}") from None
    if (checks := last_json(out)) is None:
        raise DrillError("The checks said nothing the drill could read")
    return checks


def _empty(scratch: str) -> None:
    """What the containers wrote, removed by one (they write as root); a
    copy that stays is a warning: it holds the database and its secrets."""
    try:
        runner(Path(scratch))(
            "run",
            "--rm",
            "-v",
            f"{scratch}:{SCRATCH}",
            "--entrypoint",
            "find",
            RESTIC_IMAGE,
            SCRATCH,
            "-mindepth",
            "1",
            "-delete",
        )
    except DockerError as exc:
        brand.warn(t("deploy.drill_not_emptied", path=scratch, error=exc))


def restore_drill(root: Path, server: dict[str, Any]) -> None:
    """Restore the newest off-site copy and check it; recorded on the
    server as a ``restore-drill`` event, passed or which check failed."""
    with recorded(root, server, protocol.DRILL) as said:
        began = time.monotonic()
        try:
            values = _settings(root)
            restic = {RESTIC_ENV[name]: values[name] for name in RESTIC_ENV}
            image = _app_image(root)
            step(STEPS, "restore")
            typer.echo(t("deploy.drill_restoring"))
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
                try:
                    found = json.loads(
                        _restic(scratch, restic, "snapshots", "latest", "--json")
                    )
                    if not found:  # before the first nightly copy
                        raise DrillError(t("deploy.drill_no_copy"))
                    snapshot = found[0]
                    # This one, by id: a copy sent meanwhile is not "latest" here.
                    _restic(
                        scratch, restic, "restore", snapshot["id"], "--target", SCRATCH
                    )
                    step(STEPS, "check")
                    typer.echo(t("deploy.drill_checking"))
                    checks = _check(root, image, Path(scratch), values[KEY])
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
    root = _get_project_root(project_path)
    refuse_unless_sqlite(root, "deploy.drill_not_sqlite")  # the copy is one file
    restore_drill(root, config["server"])
