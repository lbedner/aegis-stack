"""
Deploy command implementations for Aegis Stack.

Provides commands for deploying Aegis projects to remote servers,
with backup/rollback strategy and post-deploy health checks.
"""

import re
import shlex
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import typer
import yaml

from ..cli import brand
from ..constants import AnswerKeys, PostgresProviders
from ..i18n import lazy_t, t

_BACKUP_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}$")

# Headroom the image build needs. Below this a deploy is refused up front
# rather than dying inside the Dockerfile with "No space left on device".
MIN_FREE_DISK_GB = 10
# Build cache younger than this survives the post-deploy prune, so
# incremental rebuilds stay fast.
BUILD_CACHE_MAX_AGE = "168h"

# Deploy config file name
DEPLOY_CONFIG_FILE = ".aegis/deploy.yml"
DEPLOY_CONFIG_EXAMPLE = """\
# Aegis Deploy Configuration
# Run 'aegis deploy-init' to create this file interactively

server:
  host: your-server-ip
  user: root
  path: /opt/{project_name}

docker:
  context: {project_name}-remote

# Optional: domain for TLS (uncomment to enable)
# domain: example.com
# acme_email: admin@example.com

# Optional: backup settings (defaults shown)
# backup:
#   keep_count: 5
#   include_database: true

# Optional: health check after deploy (defaults shown)
# health_check:
#   retries: 3
#   auto_rollback: true
"""


def _get_project_root(project_path: str | None = None) -> Path:
    """Find the project root by looking for pyproject.toml."""
    if project_path:
        return Path(project_path)
    current = Path.cwd()
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    return Path.cwd()


def _get_project_name(project_path: str | None = None) -> str:
    """Get project name from pyproject.toml."""
    project_root = _get_project_root(project_path)
    pyproject_path = project_root / "pyproject.toml"
    if pyproject_path.exists():
        import tomllib

        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
            return data.get("project", {}).get("name", project_root.name)
    return project_root.name


def _load_deploy_config(project_path: str | None = None) -> dict | None:
    """Load deploy configuration from .aegis/deploy.yml."""
    project_root = Path(project_path) if project_path else _get_project_root()
    config_path = project_root / DEPLOY_CONFIG_FILE

    if not config_path.exists():
        return None

    with open(config_path) as f:
        return yaml.safe_load(f)


def _save_deploy_config(config: dict) -> None:
    """Save deploy configuration to .aegis/deploy.yml."""
    project_root = _get_project_root()
    config_dir = project_root / ".aegis"
    config_dir.mkdir(exist_ok=True)

    config_path = config_dir / "deploy.yml"
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)


def _is_neon_database(project_path: str | None = None) -> bool:
    """True when the project targets Neon (cloud Postgres) in production.

    Read from ``.copier-answers.yml`` (``postgres_provider``). Neon owns
    backups and recovery (branches / point-in-time restore) and runs no
    Postgres container in the prod profile, so the deploy skips the local
    ``pg_dump``/``psql`` path for these projects. Any project missing or
    unreadable answers defaults to the local-container behavior.
    """
    project_root = Path(project_path) if project_path else _get_project_root()
    answers_path = project_root / AnswerKeys.ANSWERS_FILENAME
    if not answers_path.exists():
        return False
    try:
        with open(answers_path) as f:
            answers = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return False
    return answers.get(AnswerKeys.POSTGRES_PROVIDER) == PostgresProviders.NEON


def _compose_prefix(deploy_path: str) -> str:
    """Return the docker compose command prefix for remote execution."""
    safe_path = shlex.quote(deploy_path)
    return (
        f"cd {safe_path} && "
        f"docker compose -f docker-compose.yml -f docker-compose.prod.yml"
        f" --profile prod"
    )


def _run_remote(host: str, user: str, command: str) -> subprocess.CompletedProcess:
    """Run a command on the remote server via SSH."""
    return subprocess.run(["ssh", f"{user}@{host}", command])


def _run_remote_capture(
    host: str, user: str, command: str
) -> subprocess.CompletedProcess:
    """Run a command on the remote server via SSH and capture output."""
    return subprocess.run(
        ["ssh", f"{user}@{host}", command], capture_output=True, text=True
    )


def _install_pubkey_on_server(
    pubkey: str, host: str, user: str
) -> subprocess.CompletedProcess:
    """Append a public key to the remote user's authorized_keys, idempotently.

    The pubkey is matched by full body via ``grep -F``; re-running with the
    same key is a no-op. Caller is responsible for ensuring SSH access to
    ``user@host`` already works.
    """
    pubkey_clean = pubkey.strip()
    quoted = shlex.quote(pubkey_clean)
    command = (
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
        "touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && "
        f"grep -qxF {quoted} ~/.ssh/authorized_keys || "
        f"echo {quoted} >> ~/.ssh/authorized_keys"
    )
    return subprocess.run(
        ["ssh", f"{user}@{host}", command], capture_output=True, text=True
    )


def _remove_pubkey_from_server(
    marker: str, host: str, user: str
) -> subprocess.CompletedProcess:
    """Remove any authorized_keys line containing ``marker``.

    Used to roll back a failed deploy-cd-setup. ``marker`` is the trailing
    comment on the pubkey (e.g. ``github-actions-deploy@owner/repo``).
    """
    quoted = shlex.quote(marker)
    command = (
        "if [ -f ~/.ssh/authorized_keys ]; then "
        f"  grep -vF {quoted} ~/.ssh/authorized_keys > ~/.ssh/authorized_keys.tmp || true; "
        "  mv ~/.ssh/authorized_keys.tmp ~/.ssh/authorized_keys; "
        "fi"
    )
    return subprocess.run(
        ["ssh", f"{user}@{host}", command], capture_output=True, text=True
    )


def _get_backup_config(config: dict) -> dict:
    """Extract backup config with defaults."""
    backup = config.get("backup", {}) or {}
    return {
        "keep_count": backup.get("keep_count", 5),
        "include_database": backup.get("include_database", True),
    }


def _get_health_config(config: dict) -> dict:
    """Extract health check config with defaults."""
    hc = config.get("health_check", {}) or {}
    return {
        "retries": hc.get("retries", 3),
        "auto_rollback": hc.get("auto_rollback", True),
    }


def _create_backup(
    host: str,
    user: str,
    deploy_path: str,
    include_db: bool = True,
    neon: bool = False,
) -> str | None:
    """Create a timestamped backup on the remote server.

    Returns the backup timestamp on success, None on failure.
    """
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d_%H%M%S")
    safe_path = shlex.quote(deploy_path)
    backup_dir = f"{deploy_path}/backups/{timestamp}"
    safe_backup = shlex.quote(backup_dir)

    typer.echo(t("deploy.creating_backup", timestamp=timestamp))

    # Create backup directory and copy files
    commands = [
        f"mkdir -p {safe_backup}/files",
        f"rsync -a --exclude backups {safe_path}/ {safe_backup}/files/",
    ]
    result = _run_remote_capture(host, user, " && ".join(commands))
    if result.returncode != 0:
        brand.error(t("deploy.backup_failed", error=result.stderr), err=True)
        return None

    # Database backup. Neon owns backups (branches / point-in-time restore) and
    # runs no local postgres container in the prod profile, so there is nothing
    # to pg_dump — say so explicitly instead of silently skipping (issue #765).
    if include_db and neon:
        typer.echo(t("deploy.backup_db_neon"))
    elif include_db:
        compose_prefix = _compose_prefix(deploy_path)
        # Check if postgres service exists and is running
        pg_check = _run_remote_capture(
            host, user, f"{compose_prefix} ps postgres --quiet 2>/dev/null"
        )
        if pg_check.returncode == 0 and pg_check.stdout.strip():
            typer.echo(t("deploy.backup_db"))
            db_cmd = (
                f"{compose_prefix} exec -T postgres"
                f" sh -c 'pg_dump -U $POSTGRES_USER $POSTGRES_DB'"
                f" > {safe_backup}/db_backup.sql"
            )
            db_result = _run_remote_capture(host, user, db_cmd)
            if db_result.returncode != 0:
                brand.warn(t("deploy.backup_db_failed"))

    # Write manifest
    manifest = (
        f"timestamp: {timestamp}\\n"
        f"source: {deploy_path}\\n"
        f"created: {datetime.now(UTC).isoformat()}"
    )
    _run_remote_capture(
        host, user, f"echo -e {shlex.quote(manifest)} > {safe_backup}/manifest.yml"
    )

    brand.success(t("deploy.backup_created", timestamp=timestamp))
    return timestamp


def _prune_backups(host: str, user: str, deploy_path: str, keep_count: int) -> None:
    """Remove old backups, keeping only the most recent N."""
    safe_path = shlex.quote(f"{deploy_path}/backups")
    result = _run_remote_capture(host, user, f"ls -1t {safe_path} 2>/dev/null")
    if result.returncode != 0 or not result.stdout.strip():
        return

    backups = [b.strip() for b in result.stdout.strip().splitlines() if b.strip()]
    if len(backups) <= keep_count:
        return

    to_remove = backups[keep_count:]
    for old_backup in to_remove:
        if not _BACKUP_TIMESTAMP_RE.match(old_backup):
            continue  # skip unexpected directory names
        safe_old = shlex.quote(f"{deploy_path}/backups/{old_backup}")
        _run_remote_capture(host, user, f"rm -rf {safe_old}")
        typer.echo(t("deploy.backup_pruned", name=old_backup))


def _free_disk_gb(host: str, user: str, deploy_path: str) -> int | None:
    """Free space on the filesystem holding the deploy path, in whole GB.

    ``None`` when it cannot be read - on a first deploy the path does not
    exist yet, and the preflight is a guard rather than a gate, so an
    unreadable df must never block a deploy.
    """
    safe_path = shlex.quote(deploy_path)
    result = _run_remote_capture(
        host, user, f"df -BG --output=avail {safe_path} 2>/dev/null | tail -1"
    )
    if result.returncode != 0:
        return None
    digits = "".join(c for c in result.stdout if c.isdigit())
    return int(digits) if digits else None


def _check_disk_space(host: str, user: str, deploy_path: str) -> None:
    """Refuse to start a deploy the host has no room to finish.

    Out of disk, the build dies deep inside the Dockerfile with a bare
    "No space left on device" - after files are synced, and in the rolling
    path with the queue about to be paused. Checking first turns that into
    one actionable line, before anything has been touched.
    """
    free_gb = _free_disk_gb(host, user, deploy_path)
    if free_gb is None or free_gb >= MIN_FREE_DISK_GB:
        return
    brand.error(
        t("deploy.disk_low", free=free_gb, host=host, need=MIN_FREE_DISK_GB),
        err=True,
    )
    raise typer.Exit(1)


def _prune_docker(host: str, user: str) -> None:
    """Reclaim Docker disk after a deploy has succeeded.

    Every deploy builds a new image and leaves the previous one - now
    untagged - plus its build cache behind. Nothing reclaimed them, so the
    host filled up: on one project this reached 307 images and 851 cache
    records, and the next deploy died at apt-get.

    Dangling images only, so nothing still referenced is touched, and
    rollback restores files and rebuilds rather than reusing the old image.
    ``--filter until`` rather than ``--reserved-space``, which needs
    Docker 28+. Best-effort: the new code is already serving, and
    housekeeping must not turn a good deploy into a reported failure.
    """
    typer.echo(t("deploy.pruning"))
    result = _run_remote_capture(
        host,
        user,
        "docker image prune -f >/dev/null && "
        f"docker builder prune -f --filter until={BUILD_CACHE_MAX_AGE} >/dev/null",
    )
    if result.returncode != 0:
        brand.warn(t("deploy.prune_failed"))


def _rollback_to_backup(
    host: str,
    user: str,
    deploy_path: str,
    backup_timestamp: str,
    neon: bool = False,
) -> bool:
    """Rollback to a specific backup. Returns True on success."""
    safe_path = shlex.quote(deploy_path)
    backup_dir = f"{deploy_path}/backups/{backup_timestamp}"
    safe_backup = shlex.quote(backup_dir)

    # Verify backup exists
    check = _run_remote_capture(host, user, f"test -d {safe_backup}")
    if check.returncode != 0:
        brand.error(
            t("deploy.rollback_not_found", timestamp=backup_timestamp), err=True
        )
        return False

    compose_prefix = _compose_prefix(deploy_path)

    typer.echo(t("deploy.rollback_stopping"))
    _run_remote(host, user, f"{compose_prefix} down --remove-orphans")

    typer.echo(t("deploy.rollback_restoring", timestamp=backup_timestamp))
    restore_result = _run_remote_capture(
        host,
        user,
        f"rsync -a --delete --exclude backups {safe_backup}/files/ {safe_path}/",
    )
    if restore_result.returncode != 0:
        brand.error(
            t("deploy.rollback_restore_failed", error=restore_result.stderr), err=True
        )
        return False

    # Database restore. Neon manages recovery (branches / point-in-time
    # restore); there is no local dump to replay, so report that rather than
    # silently no-op (issue #765).
    if neon:
        typer.echo(t("deploy.rollback_db_neon"))
        db_check = None
    else:
        db_check = _run_remote_capture(
            host, user, f"test -f {safe_backup}/db_backup.sql"
        )
    if db_check is not None and db_check.returncode == 0:
        typer.echo(t("deploy.rollback_db"))
        # Start only postgres first
        _run_remote(host, user, f"{compose_prefix} up -d postgres")
        typer.echo(t("deploy.rollback_pg_wait"))
        for _ in range(30):  # 60 seconds max (30 * 2s)
            ready = _run_remote_capture(
                host,
                user,
                f"{compose_prefix} exec -T postgres pg_isready -U postgres -q",
            )
            if ready.returncode == 0:
                break
            time.sleep(2)
        else:
            brand.warn(t("deploy.rollback_pg_timeout"))
        db_restore = _run_remote_capture(
            host,
            user,
            f"cat {safe_backup}/db_backup.sql |"
            f" {compose_prefix} exec -T postgres"
            f" sh -c 'psql -U $POSTGRES_USER $POSTGRES_DB'",
        )
        if db_restore.returncode != 0:
            brand.warn(t("deploy.rollback_db_failed"))

    typer.echo(t("deploy.rollback_starting"))
    start_result = _run_remote(host, user, f"{compose_prefix} up -d --build")
    if start_result.returncode != 0:
        brand.error(t("deploy.rollback_start_failed"), err=True)
        return False

    return True


def _run_health_check(
    host: str, user: str, retries: int = 3, interval: int = 5
) -> bool:
    """Run health check against the deployed application.

    Hits the public Traefik entrypoint on the droplet (port 80) rather
    than the webserver container's internal port 8000 — that port isn't
    published to the host in prod compose, so the old `localhost:8000`
    check always produced a false negative. Going through Traefik also
    validates the full routing path the real users hit (container health
    + docker labels + Traefik registration).
    """
    typer.echo(t("deploy.health_waiting"))
    time.sleep(10)

    for attempt in range(1, retries + 1):
        typer.echo(t("deploy.health_attempt", n=attempt, total=retries))
        result = _run_remote_capture(
            host,
            user,
            "curl -sf --max-time 10 http://localhost/health/ -o /dev/null",
        )
        if result.returncode == 0:
            brand.success(t("deploy.health_passed"))
            return True

        if attempt < retries:
            typer.echo(t("deploy.health_retry", interval=interval))
            time.sleep(interval)

    brand.error(t("deploy.health_all_failed"), err=True)
    return False


# ---------------------------------------------------------------------------
# Rolling deploy (code-only, zero HTTP downtime)
# ---------------------------------------------------------------------------

ROLLING_PAUSE_KEY = "aegis:queue:paused"
ROLLING_DRAIN_TIMEOUT_DEFAULT = 90  # seconds
ROLLING_DRAIN_POLL_SECONDS = 1
ROLLING_HEALTH_POLL_SECONDS = 2
# Runaway-guard ceiling for the webserver health-poll swap. The
# container's own HEALTHCHECK budget (start_period + retries x interval)
# normally decides success (healthy) or failure (unhealthy); this is only
# a hard cap against a container that never settles either way. It is
# deliberately long so a slow-but-healthy boot is never killed by a wall
# clock — the bug that made docker-rollout's 60s default fickle.
ROLLING_ROLLOUT_TIMEOUT_DEFAULT = 900  # seconds


def _rolling_compose_prefix(deploy_path: str) -> str:
    """Compose prefix that omits ``--profile prod`` so per-service
    ``up -d --no-deps`` targeting works for prod profile and
    profile-less services alike.
    """
    safe_path = shlex.quote(deploy_path)
    return (
        f"cd {safe_path} && "
        f"docker compose -f docker-compose.yml -f docker-compose.prod.yml"
    )


def _rolling_scale_command(deploy_path: str, replicas: int) -> str:
    """Build the ``docker compose up --scale webserver=N`` command.

    ``--no-recreate`` keeps the existing (old) container untouched so HTTP
    keeps flowing through Traefik while the new replica boots; ``--no-deps``
    leaves database / redis / traefik alone. Scaling up to 2 starts a
    second replica from the freshly-built image; scaling back to 1 settles
    on the survivor.
    """
    prefix = _rolling_compose_prefix(deploy_path)
    return (
        f"{prefix} up -d --no-deps --no-recreate --scale webserver={replicas} webserver"
    )


def _rolling_inspect_health_command(container_id: str) -> str:
    """Build the ``docker inspect`` command that prints a container's
    health status, falling back to its run state when no HEALTHCHECK is
    defined (``healthy``/``unhealthy``/``starting`` vs ``running``/``exited``).
    """
    fmt = "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}"
    return f"docker inspect --format {shlex.quote(fmt)} {shlex.quote(container_id)}"


def _rolling_health_verdict(raw_status: str) -> str:
    """Map raw ``docker inspect`` output to ``healthy``/``unhealthy``/``starting``.

    Only an explicit ``unhealthy``/``exited``/``dead`` verdict rolls a deploy
    back; everything still settling (``starting``, ``created``, empty,
    ``<no value>``) keeps polling, so a slow-but-healthy boot is never
    killed by a wall clock.
    """
    status = raw_status.strip().strip('"').lower()
    if status in ("healthy", "running"):
        return "healthy"
    if status in ("unhealthy", "exited", "dead"):
        return "unhealthy"
    return "starting"


def _rolling_running_services(host: str, user: str, deploy_path: str) -> set[str]:
    """Return the set of currently-running compose service names."""
    prefix = _rolling_compose_prefix(deploy_path)
    result = _run_remote_capture(
        host, user, f"{prefix} ps --services --filter status=running"
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _rolling_clear_pause(host: str, user: str, deploy_path: str) -> None:
    """Best-effort clear of the queue-pause flag. Safe to call repeatedly."""
    prefix = _rolling_compose_prefix(deploy_path)
    subprocess.run(
        [
            "ssh",
            f"{user}@{host}",
            f"{prefix} exec -T redis redis-cli DEL {ROLLING_PAUSE_KEY} >/dev/null 2>&1 || true",
        ],
        capture_output=True,
    )


def _rolling_wait_for_drain(
    host: str, user: str, deploy_path: str, timeout_seconds: int
) -> bool:
    """Poll ``SCAN worker:*:busy`` until empty or timeout.

    Returns True if workers drained, False on timeout. The check works
    for any worker library that registers per-job heartbeat keys with
    that prefix (taskiq today, dramatiq / arq via the template's
    heartbeat module).
    """
    prefix = _rolling_compose_prefix(deploy_path)
    drain_script = (
        f"deadline=$(( $(date +%s) + {timeout_seconds} )); "
        "while : ; do "
        f"  busy=$({prefix} exec -T redis redis-cli --scan --pattern 'worker:*:busy' | tr -d '\\r' | sed '/^$/d'); "
        '  if [ -z "$busy" ]; then echo drained; exit 0; fi; '
        '  if [ "$(date +%s)" -ge "$deadline" ]; then '
        '    echo "drain timeout; still busy:" >&2; echo "$busy" >&2; exit 1; '
        "  fi; "
        f"  sleep {ROLLING_DRAIN_POLL_SECONDS}; "
        "done"
    )
    result = _run_remote(host, user, drain_script)
    return result.returncode == 0


def _rolling_webserver_ids(host: str, user: str, deploy_path: str) -> list[str]:
    """Return the container IDs currently backing the ``webserver`` service."""
    prefix = _rolling_compose_prefix(deploy_path)
    result = _run_remote_capture(host, user, f"{prefix} ps -q webserver")
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _rolling_container_health(host: str, user: str, container_id: str) -> str:
    """Inspect a container and return ``healthy``/``unhealthy``/``starting``."""
    result = _run_remote_capture(
        host, user, _rolling_inspect_health_command(container_id)
    )
    return _rolling_health_verdict(result.stdout)


def _rolling_remove_container(host: str, user: str, container_id: str) -> None:
    """Stop and remove a single container, best-effort.

    ``docker rm -f`` sends SIGTERM (uvicorn drains in-flight requests) then
    SIGKILL after the grace period. Safe to call on an already-gone id.
    """
    safe = shlex.quote(container_id)
    _run_remote(host, user, f"docker rm -f {safe} >/dev/null 2>&1 || true")


def _rolling_swap_webserver(
    host: str, user: str, deploy_path: str, ceiling_seconds: int
) -> bool:
    """Zero-downtime webserver swap driven by HEALTHCHECK status polling.

    Brings up a second replica from the freshly-built image alongside the
    old one (Traefik load-balances both), polls the new container's health
    until it reports ``healthy``, then drains the old container and scales
    back to one. If the new container goes ``unhealthy`` (driven by the
    compose HEALTHCHECK's own ``retries x interval`` budget) or never
    settles within ``ceiling_seconds`` (a runaway guard), the new replica
    is removed and the old one keeps serving.

    Replaces the external ``docker-rollout`` plugin: the container's own
    HEALTHCHECK is the single source of truth for "is it up?", so a
    slow-but-healthy boot is no longer rolled back by a wall clock, and no
    extra tooling needs to be installed on the deploy host.

    The old container(s) are never touched until the new replica reports
    healthy, so on any failure path the previous version keeps serving.
    Returns True on a successful swap, False otherwise.
    """
    before = _rolling_webserver_ids(host, user, deploy_path)
    if not before:
        return False
    before_set = set(before)

    # Add exactly one new replica from the freshly-built image, keeping the
    # old container(s) running (--no-recreate). Scaling relative to the
    # current count avoids a no-op when the service is already past one.
    scale_up = _run_remote(
        host, user, _rolling_scale_command(deploy_path, len(before) + 1)
    )
    if scale_up.returncode != 0:
        return False

    after = _rolling_webserver_ids(host, user, deploy_path)
    new_ids = [cid for cid in after if cid not in before_set]
    if len(new_ids) != 1:
        # Couldn't isolate a single new replica — undo and bail. The old
        # container(s) were never touched, so HTTP keeps serving.
        for cid in new_ids:
            _rolling_remove_container(host, user, cid)
        _run_remote(host, user, _rolling_scale_command(deploy_path, len(before)))
        return False
    new_id = new_ids[0]

    # Poll the new replica's health until healthy / unhealthy / ceiling.
    deadline = time.monotonic() + ceiling_seconds
    while True:
        verdict = _rolling_container_health(host, user, new_id)
        if verdict == "healthy":
            break
        if verdict == "unhealthy" or time.monotonic() >= deadline:
            _rolling_remove_container(host, user, new_id)
            _run_remote(host, user, _rolling_scale_command(deploy_path, len(before)))
            return False
        time.sleep(ROLLING_HEALTH_POLL_SECONDS)

    # New replica healthy: drain the old container(s), settle back to one.
    for old_id in before:
        _rolling_remove_container(host, user, old_id)
    scale_down = _run_remote(host, user, _rolling_scale_command(deploy_path, 1))
    return scale_down.returncode == 0


def _run_rolling_deploy(
    host: str,
    user: str,
    deploy_path: str,
    project_root: Path,
    build: bool,
    health_check: bool,
    health_cfg: dict,
    drain_timeout: int,
    rollout_timeout: int,
) -> None:
    """Zero-HTTP-downtime deploy of code-only changes.

    The webserver rolls by starting a second replica and health-polling it
    (``rollout_timeout`` is only a runaway-guard ceiling; the container's
    own HEALTHCHECK budget decides success) so HTTP keeps serving the old
    container until the new one is healthy. Scheduler and workers hard-
    restart, but the worker queue is paused first so in-flight jobs
    complete cleanly instead of being SIGTERMed. Database, Redis, and
    Traefik are untouched.

    Skips DB migrations — use the standard ``aegis deploy`` for those.
    """
    brand.accent(t("deploy.rolling_starting", host=host), bold=True)

    # Step 1: rsync working tree
    typer.echo(t("deploy.syncing"))
    rsync_result = subprocess.run(
        [
            "rsync",
            "-avz",
            "--exclude",
            ".git",
            "--exclude",
            "__pycache__",
            "--exclude",
            ".venv",
            "--exclude",
            "*.pyc",
            "--exclude",
            ".pytest_cache",
            "--exclude",
            ".ruff_cache",
            "--exclude",
            "data/",
            "--exclude",
            ".env",
            "--exclude",
            ".env.deploy",
            "--exclude",
            ".aegis/",
            "--exclude",
            "backups/",
            "--exclude",
            "node_modules/",
            f"{project_root}/",
            f"{user}@{host}:{deploy_path}/",
        ]
    )
    if rsync_result.returncode != 0:
        brand.error(t("deploy.sync_failed"), err=True)
        raise typer.Exit(1)

    # Step 2: scp .env (prefer .env.deploy)
    deploy_env_file = project_root / ".env.deploy"
    dev_env_file = project_root / ".env"
    env_file: Path | None = None
    if deploy_env_file.exists():
        env_file = deploy_env_file
    elif dev_env_file.exists():
        env_file = dev_env_file

    if env_file is not None:
        typer.echo(t("deploy.copying_env", file=env_file.name))
        safe_path = shlex.quote(f"{deploy_path}/.env")
        env_result = subprocess.run(
            ["scp", str(env_file), f"{user}@{host}:{safe_path}"]
        )
        if env_result.returncode != 0:
            brand.error(t("deploy.env_copy_failed"), err=True)
            raise typer.Exit(1)

    prefix = _rolling_compose_prefix(deploy_path)
    running = _rolling_running_services(host, user, deploy_path)
    worker_services = sorted(
        s for s in running if s.startswith("worker-") or s == "scheduler"
    )
    has_webserver = "webserver" in running

    # Step 3: build the webserver image (new code lands here)
    if build and has_webserver:
        typer.echo(t("deploy.rolling_building"))
        build_result = _run_remote(host, user, f"{prefix} build webserver")
        if build_result.returncode != 0:
            brand.error(t("deploy.start_failed"), err=True)
            raise typer.Exit(1)

    # Step 4 + 5: pause the queue and wait for in-flight jobs to drain
    pause_set = False
    if worker_services and any(s.startswith("worker-") for s in worker_services):
        typer.echo(t("deploy.rolling_pausing"))
        pause_result = _run_remote(
            host,
            user,
            f"{prefix} exec -T redis redis-cli SET {ROLLING_PAUSE_KEY} 1 >/dev/null",
        )
        pause_set = pause_result.returncode == 0
        if not pause_set:
            brand.warn(t("deploy.rolling_pause_failed"))

    try:
        if pause_set:
            typer.echo(t("deploy.rolling_draining", seconds=drain_timeout))
            if not _rolling_wait_for_drain(host, user, deploy_path, drain_timeout):
                brand.error(t("deploy.rolling_drain_timeout"), err=True)
                raise typer.Exit(1)

        # Step 6: recreate scheduler + workers (no --deps so deps stay up)
        if worker_services:
            typer.echo(
                t("deploy.rolling_recreating", services=" ".join(worker_services))
            )
            recreate = _run_remote(
                host,
                user,
                f"{prefix} up -d --force-recreate --no-deps {' '.join(worker_services)}",
            )
            if recreate.returncode != 0:
                brand.error(t("deploy.start_failed"), err=True)
                raise typer.Exit(1)

        # Step 7: roll the webserver by health-polling a new replica
        if has_webserver:
            typer.echo(t("deploy.rolling_webserver", seconds=rollout_timeout))
            if not _rolling_swap_webserver(host, user, deploy_path, rollout_timeout):
                brand.error(t("deploy.rolling_rollout_failed"), err=True)
                raise typer.Exit(1)
    finally:
        # Step 8: always clear the pause flag — never wedge workers
        if pause_set:
            _rolling_clear_pause(host, user, deploy_path)

    # Step 9: health check
    if health_check:
        healthy = _run_health_check(host, user, retries=health_cfg["retries"])
        if not healthy:
            brand.warn(t("deploy.health_failed_hint"))
            raise typer.Exit(1)

    _prune_docker(host, user)

    brand.success(f"\n{t('deploy.rolling_complete')}", bold=True)
    typer.echo(t("deploy.app_running", host=host))


# ---------------------------------------------------------------------------
# CLI Commands
# ---------------------------------------------------------------------------


def deploy_init_command(
    host: str | None = typer.Option(
        None, "--host", "-h", help=lazy_t("deploy.help_opt_host")
    ),
    user: str = typer.Option(
        "root", "--user", "-u", help=lazy_t("deploy.help_opt_user")
    ),
    path: str | None = typer.Option(
        None, "--path", "-p", help=lazy_t("deploy.help_opt_path")
    ),
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
) -> None:
    """
    Initialize deployment configuration for this project.

    Creates .aegis/deploy.yml with server connection settings.

    Examples:\\n
        - aegis deploy-init --host 192.168.1.100\\n
        - aegis deploy-init --host myserver.com --user deploy\\n
    """
    project_name = _get_project_name(project_path)
    project_root = _get_project_root(project_path)

    # Interactive prompts if not provided
    if not host:
        host = typer.prompt(t("deploy.prompt_host"))

    if not path:
        path = f"/opt/{project_name}"

    config = {
        "server": {
            "host": host,
            "user": user,
            "path": path,
        },
        "docker": {
            "context": f"{project_name}-remote",
        },
    }

    _save_deploy_config(config)

    brand.success(f"\n{t('deploy.init_saved', file=DEPLOY_CONFIG_FILE)}")
    typer.echo(t("deploy.init_host", host=host))
    typer.echo(t("deploy.init_user", user=user))
    typer.echo(t("deploy.init_path", path=path))
    typer.echo(t("deploy.init_docker_context", context=f"{project_name}-remote"))

    # Check if .aegis is in .gitignore
    gitignore_path = project_root / ".gitignore"
    if gitignore_path.exists():
        content = gitignore_path.read_text()
        if ".aegis/" not in content and ".aegis" not in content:
            brand.warn(t("deploy.init_gitignore"))


def deploy_setup_command(
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
    public_key: str | None = typer.Option(
        None,
        "--public-key",
        help=lazy_t("deploy.help_opt_public_key"),
    ),
) -> None:
    """
    Provision a remote server for deployment.

    Installs Docker, configures firewall, and prepares the server.
    Run this once on a fresh server before deploying.

    Examples:\\n
        - aegis deploy-setup\\n
        - aegis deploy-setup --public-key ~/.ssh/id_ed25519.pub\\n
    """
    config = _load_deploy_config(project_path)
    if not config:
        brand.error(t("deploy.no_config"), err=True)
        raise typer.Exit(1)

    host = config["server"]["host"]
    user = config["server"]["user"]

    project_root = Path(project_path) if project_path else _get_project_root()
    setup_script = project_root / "scripts" / "server-setup.sh"

    if not setup_script.exists():
        brand.error(t("deploy.setup_script_missing", path=setup_script), err=True)
        typer.echo(t("deploy.setup_script_hint"))
        raise typer.Exit(1)

    brand.accent(t("deploy.setup_title", target=f"{user}@{host}"), bold=True)

    # Add host key to known_hosts if needed
    typer.echo(t("deploy.checking_ssh"))
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            f"{user}@{host}",
            "echo ok",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        if "Host key verification failed" in result.stderr:
            typer.echo(t("deploy.adding_host_key"))
            keyscan_result = subprocess.run(
                ["ssh-keyscan", "-H", host],
                capture_output=True,
                text=True,
            )
            if keyscan_result.returncode != 0:
                brand.error(
                    t("deploy.ssh_keyscan_failed", error=keyscan_result.stderr),
                    err=True,
                )
                raise typer.Exit(1)
            known_hosts = Path.home() / ".ssh" / "known_hosts"
            with open(known_hosts, "a") as f:
                f.write(keyscan_result.stdout)
        else:
            brand.error(t("deploy.ssh_failed", error=result.stderr), err=True)
            raise typer.Exit(1)

    # Copy and run setup script
    typer.echo(t("deploy.copying_script"))
    scp_result = subprocess.run(
        ["scp", str(setup_script), f"{user}@{host}:/tmp/server-setup.sh"]
    )
    if scp_result.returncode != 0:
        brand.error(t("deploy.copy_failed"), err=True)
        raise typer.Exit(1)

    typer.echo(t("deploy.running_setup"))
    ssh_result = subprocess.run(
        [
            "ssh",
            f"{user}@{host}",
            "chmod +x /tmp/server-setup.sh && /tmp/server-setup.sh",
        ]
    )
    if ssh_result.returncode != 0:
        brand.error(t("deploy.setup_failed"), err=True)
        raise typer.Exit(1)

    # Verify installation on remote server
    deploy_path = config["server"]["path"]
    typer.echo("")
    typer.echo(t("deploy.setup_verify"))
    docker_ver = _run_remote_capture(host, user, "docker --version")
    typer.echo(t("deploy.setup_verify_docker", version=docker_ver.stdout.strip()))
    compose_ver = _run_remote_capture(host, user, "docker compose version")
    typer.echo(t("deploy.setup_verify_compose", version=compose_ver.stdout.strip()))
    uv_ver = _run_remote_capture(host, user, "PATH=$HOME/.local/bin:$PATH uv --version")
    typer.echo(t("deploy.setup_verify_uv", version=uv_ver.stdout.strip()))
    typer.echo(t("deploy.setup_verify_app_dir", path=deploy_path))

    if public_key:
        pubkey_path = Path(public_key).expanduser()
        if not pubkey_path.exists():
            brand.error(t("deploy.pubkey_missing", path=str(pubkey_path)), err=True)
            raise typer.Exit(1)
        pubkey_body = pubkey_path.read_text().strip()
        typer.echo(t("deploy.installing_pubkey", user=user))
        install_result = _install_pubkey_on_server(pubkey_body, host, user)
        if install_result.returncode != 0:
            brand.error(
                t("deploy.pubkey_install_failed", error=install_result.stderr), err=True
            )
            raise typer.Exit(1)
        brand.success(t("deploy.pubkey_installed"))

    brand.success(f"\n{t('deploy.setup_complete')}", bold=True)
    typer.echo(t("deploy.setup_next"))


def deploy_command(
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
    build: bool = typer.Option(
        True, "--build/--no-build", help=lazy_t("deploy.help_opt_build")
    ),
    backup: bool = typer.Option(
        True, "--backup/--no-backup", help=lazy_t("deploy.help_opt_backup")
    ),
    health_check: bool = typer.Option(
        True,
        "--health-check/--no-health-check",
        help=lazy_t("deploy.help_opt_health"),
    ),
    rolling: bool = typer.Option(
        False,
        "--rolling",
        help=lazy_t("deploy.help_opt_rolling"),
    ),
    drain_timeout: int = typer.Option(
        ROLLING_DRAIN_TIMEOUT_DEFAULT,
        "--drain-timeout",
        help=lazy_t("deploy.help_opt_drain_timeout"),
    ),
    rollout_timeout: int = typer.Option(
        ROLLING_ROLLOUT_TIMEOUT_DEFAULT,
        "--rollout-timeout",
        help=lazy_t("deploy.help_opt_rollout_timeout"),
    ),
) -> None:
    """
    Deploy the project to the configured server.

    Syncs files, builds Docker images, and starts services.
    Automatically creates a backup before deploying and runs a health
    check afterward. If the health check fails, auto-rollback restores
    the previous version.

    Pass ``--rolling`` for zero-HTTP-downtime code-only deploys: the
    webserver rolls over by health-polling a new replica and the worker
    queue is paused so in-flight jobs finish cleanly before workers
    restart. Skips DB migrations — use the standard path for those.

    Examples:\\n
        - aegis deploy\\n
        - aegis deploy --no-build\\n
        - aegis deploy --no-backup --no-health-check\\n
        - aegis deploy --rolling\\n
    """
    config = _load_deploy_config(project_path)
    if not config:
        brand.error(t("deploy.no_config"), err=True)
        raise typer.Exit(1)

    host = config["server"]["host"]
    user = config["server"]["user"]
    deploy_path = config["server"]["path"]
    backup_cfg = _get_backup_config(config)
    health_cfg = _get_health_config(config)
    neon = _is_neon_database(project_path)

    project_root = Path(project_path) if project_path else _get_project_root()

    # Before either path touches the server: a build needs room to land.
    _check_disk_space(host, user, deploy_path)

    if rolling:
        _run_rolling_deploy(
            host=host,
            user=user,
            deploy_path=deploy_path,
            project_root=project_root,
            build=build,
            health_check=health_check,
            health_cfg=health_cfg,
            drain_timeout=drain_timeout,
            rollout_timeout=rollout_timeout,
        )
        return

    brand.accent(t("deploy.deploying", host=host), bold=True)

    # Step 1: Create backup before deploying
    backup_timestamp: str | None = None
    if backup:
        # Check if there's an existing deployment to back up
        check = _run_remote_capture(
            host, user, f"test -f {shlex.quote(deploy_path)}/docker-compose.yml"
        )
        if check.returncode == 0:
            backup_timestamp = _create_backup(
                host,
                user,
                deploy_path,
                include_db=backup_cfg["include_database"],
                neon=neon,
            )
            if backup_timestamp:
                _prune_backups(host, user, deploy_path, backup_cfg["keep_count"])
        else:
            typer.echo(t("deploy.no_existing"))

    # Step 2: Sync files to server
    typer.echo(t("deploy.syncing"))
    mkdir_result = subprocess.run(
        ["ssh", f"{user}@{host}", f"mkdir -p {shlex.quote(deploy_path)}"]
    )
    if mkdir_result.returncode != 0:
        brand.error(t("deploy.mkdir_failed", path=deploy_path), err=True)
        raise typer.Exit(1)

    rsync_result = subprocess.run(
        [
            "rsync",
            "-avz",
            "--exclude",
            ".git",
            "--exclude",
            "__pycache__",
            "--exclude",
            ".venv",
            "--exclude",
            "*.pyc",
            "--exclude",
            ".pytest_cache",
            "--exclude",
            ".ruff_cache",
            "--exclude",
            "data/",
            "--exclude",
            ".env",
            "--exclude",
            ".env.deploy",
            "--exclude",
            ".aegis/",
            "--exclude",
            "backups/",
            "--exclude",
            "node_modules/",
            f"{project_root}/",
            f"{user}@{host}:{deploy_path}/",
        ]
    )
    if rsync_result.returncode != 0:
        brand.error(t("deploy.sync_failed"), err=True)
        raise typer.Exit(1)

    # Step 3: Copy .env file (prefer .env.deploy for production values)
    deploy_env_file = project_root / ".env.deploy"
    dev_env_file = project_root / ".env"
    if deploy_env_file.exists():
        env_file = deploy_env_file
    elif dev_env_file.exists():
        env_file = dev_env_file
    else:
        env_file = None

    if env_file is not None:
        typer.echo(t("deploy.copying_env", file=env_file.name))
        safe_path = shlex.quote(f"{deploy_path}/.env")
        env_result = subprocess.run(
            ["scp", str(env_file), f"{user}@{host}:{safe_path}"]
        )
        if env_result.returncode != 0:
            brand.error(t("deploy.env_copy_failed"), err=True)
            raise typer.Exit(1)

    # Step 4: Stop existing services
    typer.echo(t("deploy.stopping"))
    compose_prefix = _compose_prefix(deploy_path)
    _run_remote(host, user, f"{compose_prefix} down --remove-orphans")

    # Step 5: Build and start services
    typer.echo(t("deploy.building"))
    build_flag = "--build" if build else ""
    compose_cmd = f"{compose_prefix} up -d {build_flag}"
    compose_result = subprocess.run(["ssh", f"{user}@{host}", compose_cmd])
    if compose_result.returncode != 0:
        brand.error(t("deploy.start_failed"), err=True)
        if backup_timestamp and health_cfg["auto_rollback"]:
            brand.warn(t("deploy.auto_rollback"))
            _rollback_to_backup(host, user, deploy_path, backup_timestamp, neon=neon)
        raise typer.Exit(1)

    # Step 6: Restart Traefik if present
    prefix = _compose_prefix(deploy_path)
    traefik_check = subprocess.run(
        ["ssh", f"{user}@{host}", f"{prefix} ps traefik --quiet 2>/dev/null"],
        capture_output=True,
    )
    if traefik_check.returncode == 0:
        _run_remote(host, user, f"{prefix} restart traefik")

    # Step 7: Health check + auto-rollback
    if health_check:
        healthy = _run_health_check(
            host,
            user,
            retries=health_cfg["retries"],
        )
        if not healthy:
            if backup_timestamp and health_cfg["auto_rollback"]:
                brand.warn(t("deploy.auto_rollback"), bold=True)
                success = _rollback_to_backup(
                    host, user, deploy_path, backup_timestamp, neon=neon
                )
                if success:
                    brand.success(t("deploy.rolled_back", timestamp=backup_timestamp))
                else:
                    brand.error(t("deploy.rollback_failed"), err=True)
                raise typer.Exit(1)
            else:
                brand.warn(t("deploy.health_failed_hint"))
                raise typer.Exit(1)

    _prune_docker(host, user)

    brand.success(f"\n{t('deploy.complete')}", bold=True)
    typer.echo(t("deploy.app_running", host=host))
    typer.echo(t("deploy.overseer", host=host))
    typer.echo(t("deploy.view_logs"))
    typer.echo(t("deploy.check_status"))


def deploy_backup_command(
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
) -> None:
    """
    Create a backup of the currently deployed application.

    Snapshots application files and optionally the database
    on the remote server.

    Examples:\\n
        - aegis deploy-backup\\n
    """
    config = _load_deploy_config(project_path)
    if not config:
        brand.error(t("deploy.no_config"), err=True)
        raise typer.Exit(1)

    host = config["server"]["host"]
    user = config["server"]["user"]
    deploy_path = config["server"]["path"]
    backup_cfg = _get_backup_config(config)

    brand.accent(t("deploy.creating_backup_on", host=host), bold=True)

    timestamp = _create_backup(
        host,
        user,
        deploy_path,
        include_db=backup_cfg["include_database"],
        neon=_is_neon_database(project_path),
    )
    if not timestamp:
        raise typer.Exit(1)

    _prune_backups(host, user, deploy_path, backup_cfg["keep_count"])
    brand.success(f"\n{t('deploy.backup_complete')}", bold=True)


def deploy_backups_command(
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
) -> None:
    """
    List available deployment backups.

    Shows timestamps, sizes, and whether a database dump is included.

    Examples:\\n
        - aegis deploy-backups\\n
    """
    config = _load_deploy_config(project_path)
    if not config:
        brand.error(t("deploy.no_config"), err=True)
        raise typer.Exit(1)

    host = config["server"]["host"]
    user = config["server"]["user"]
    deploy_path = config["server"]["path"]

    safe_path = shlex.quote(f"{deploy_path}/backups")
    result = _run_remote_capture(host, user, f"ls -1t {safe_path} 2>/dev/null")

    if result.returncode != 0 or not result.stdout.strip():
        typer.echo(t("deploy.no_backups"))
        return

    backups = [b.strip() for b in result.stdout.strip().splitlines() if b.strip()]

    brand.accent(
        f"{t('deploy.backups_header', host=host, count=len(backups))}\n", bold=True
    )
    ts = t("deploy.col_timestamp")
    sz = t("deploy.col_size")
    db = t("deploy.col_database")
    typer.echo(f"  {ts:<24} {sz:<12} {db}")
    typer.echo(f"  {'─' * 24} {'─' * 12} {'─' * 10}")

    for backup_name in backups:
        backup_dir = f"{deploy_path}/backups/{backup_name}"
        safe_dir = shlex.quote(backup_dir)

        # Get size
        size_result = _run_remote_capture(
            host, user, f"du -sh {safe_dir} 2>/dev/null | cut -f1"
        )
        size = size_result.stdout.strip() if size_result.returncode == 0 else "?"

        # Check for DB dump
        db_check = _run_remote_capture(host, user, f"test -f {safe_dir}/db_backup.sql")
        has_db = "yes" if db_check.returncode == 0 else "no"

        typer.echo(f"  {backup_name:<24} {size:<12} {has_db}")

    typer.echo(f"\n{t('deploy.rollback_hint')}")


def deploy_rollback_command(
    backup: str | None = typer.Option(
        None, "--backup", "-b", help=lazy_t("deploy.help_opt_rollback_backup")
    ),
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
) -> None:
    """
    Rollback to a previous deployment backup.

    Restores application files and database from a backup snapshot.
    Uses the latest backup if no specific timestamp is provided.

    Examples:\\n
        - aegis deploy-rollback\\n
        - aegis deploy-rollback --backup 2026-03-10_183045\\n
    """
    config = _load_deploy_config(project_path)
    if not config:
        brand.error(t("deploy.no_config"), err=True)
        raise typer.Exit(1)

    host = config["server"]["host"]
    user = config["server"]["user"]
    deploy_path = config["server"]["path"]

    # Find backup to use
    if not backup:
        safe_path = shlex.quote(f"{deploy_path}/backups")
        result = _run_remote_capture(
            host, user, f"ls -1t {safe_path} 2>/dev/null | head -1"
        )
        if result.returncode != 0 or not result.stdout.strip():
            brand.error(t("deploy.no_backups_available"), err=True)
            raise typer.Exit(1)
        backup = result.stdout.strip()

    brand.warn(t("deploy.rolling_back", backup=backup, host=host), bold=True)

    success = _rollback_to_backup(
        host, user, deploy_path, backup, neon=_is_neon_database(project_path)
    )
    if success:
        # Restart Traefik if present
        prefix = _compose_prefix(deploy_path)
        traefik_check = subprocess.run(
            ["ssh", f"{user}@{host}", f"{prefix} ps traefik --quiet 2>/dev/null"],
            capture_output=True,
        )
        if traefik_check.returncode == 0:
            _run_remote(host, user, f"{prefix} restart traefik")

        brand.success(f"\n{t('deploy.rollback_complete')}", bold=True)
        typer.echo(t("deploy.check_status"))
        typer.echo(t("deploy.view_logs"))
    else:
        brand.error(t("deploy.rollback_failed_final"), err=True)
        raise typer.Exit(1)


def deploy_logs_command(
    follow: bool = typer.Option(
        True, "--follow/--no-follow", "-f", help=lazy_t("deploy.help_opt_logs_follow")
    ),
    service: str | None = typer.Option(
        None, "--service", "-s", help=lazy_t("deploy.help_opt_logs_service")
    ),
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
) -> None:
    """
    View logs from the deployed application.

    Examples:\\n
        - aegis deploy-logs\\n
        - aegis deploy-logs --no-follow\\n
        - aegis deploy-logs --service webserver\\n
    """
    config = _load_deploy_config(project_path)
    if not config:
        brand.error(t("deploy.no_config"), err=True)
        raise typer.Exit(1)

    host = config["server"]["host"]
    user = config["server"]["user"]
    deploy_path = config["server"]["path"]

    follow_flag = "-f" if follow else ""
    service_arg = service if service else ""
    cmd = f"{_compose_prefix(deploy_path)} logs {follow_flag} {service_arg}"
    _run_remote(host, user, cmd)


def deploy_status_command(
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
) -> None:
    """
    Check the status of deployed services.

    Examples:\\n
        - aegis deploy-status\\n
    """
    config = _load_deploy_config(project_path)
    if not config:
        brand.error(t("deploy.no_config"), err=True)
        raise typer.Exit(1)

    host = config["server"]["host"]
    user = config["server"]["user"]
    deploy_path = config["server"]["path"]

    brand.accent(t("deploy.status_header", host=host), bold=True)
    _run_remote(host, user, f"{_compose_prefix(deploy_path)} ps")


def deploy_stop_command(
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
) -> None:
    """
    Stop all deployed services.

    Examples:\\n
        - aegis deploy-stop\\n
    """
    config = _load_deploy_config(project_path)
    if not config:
        brand.error(t("deploy.no_config"), err=True)
        raise typer.Exit(1)

    host = config["server"]["host"]
    user = config["server"]["user"]
    deploy_path = config["server"]["path"]

    brand.warn(t("deploy.stop_stopping"))
    result = _run_remote(host, user, f"{_compose_prefix(deploy_path)} down")
    if result.returncode == 0:
        brand.success(t("deploy.stop_success"))
    else:
        brand.error(t("deploy.stop_failed"), err=True)
        raise typer.Exit(1)


def deploy_restart_command(
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
) -> None:
    """
    Restart all deployed services.

    Examples:\\n
        - aegis deploy-restart\\n
    """
    config = _load_deploy_config(project_path)
    if not config:
        brand.error(t("deploy.no_config"), err=True)
        raise typer.Exit(1)

    host = config["server"]["host"]
    user = config["server"]["user"]
    deploy_path = config["server"]["path"]

    brand.warn(t("deploy.restart_restarting"))
    result = _run_remote(host, user, f"{_compose_prefix(deploy_path)} restart")
    if result.returncode == 0:
        brand.success(t("deploy.restart_success"))
    else:
        brand.error(t("deploy.restart_failed"), err=True)
        raise typer.Exit(1)


def deploy_shell_command(
    service: str = typer.Option(
        "webserver", "--service", "-s", help=lazy_t("deploy.help_opt_shell_service")
    ),
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
) -> None:
    """
    Open a shell in a deployed container.

    Examples:\\n
        - aegis deploy-shell\\n
        - aegis deploy-shell --service redis\\n
    """
    config = _load_deploy_config(project_path)
    if not config:
        brand.error(t("deploy.no_config"), err=True)
        raise typer.Exit(1)

    host = config["server"]["host"]
    user = config["server"]["user"]
    deploy_path = config["server"]["path"]

    # Use -t for interactive TTY
    subprocess.run(
        [
            "ssh",
            "-t",
            f"{user}@{host}",
            f"{_compose_prefix(deploy_path)} exec {service} /bin/bash",
        ]
    )


# ─────────────────────────── deploy-cd-setup ───────────────────────────


_GH_DEPLOY_KEY_SECRET = "DEPLOY_SSH_KEY"
_GH_DEPLOY_HOST_SECRET = "DEPLOY_HOST"
_GH_DEPLOY_USER_SECRET = "DEPLOY_USER"


def _detect_github_repo(project_root: Path) -> str | None:
    """Parse owner/repo from ``git remote get-url origin`` in project_root.

    Returns ``None`` if not a git repo, no origin, or origin isn't GitHub.
    Accepts both SSH (``git@github.com:owner/repo.git``) and HTTPS
    (``https://github.com/owner/repo.git``) forms.
    """
    result = subprocess.run(
        ["git", "-C", str(project_root), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    match = re.match(
        r"^(?:git@github\.com:|https://github\.com/)([^/]+)/([^/]+?)(?:\.git)?/?$",
        url,
    )
    return f"{match.group(1)}/{match.group(2)}" if match else None


def _check_gh_cli() -> None:
    """Verify ``gh`` CLI is installed and authenticated; exit on failure."""
    try:
        version = subprocess.run(["gh", "--version"], capture_output=True)
    except FileNotFoundError:
        brand.error(t("deploy.cd_gh_not_installed"), err=True)
        raise typer.Exit(1) from None
    if version.returncode != 0:
        brand.error(t("deploy.cd_gh_not_installed"), err=True)
        raise typer.Exit(1)
    try:
        auth = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    except FileNotFoundError:
        brand.error(t("deploy.cd_gh_not_installed"), err=True)
        raise typer.Exit(1) from None
    if auth.returncode != 0:
        brand.error(t("deploy.cd_gh_not_authed"), err=True)
        raise typer.Exit(1)


def _list_gh_secrets(repo: str) -> set[str]:
    """Return the set of secret names already configured on ``repo``."""
    result = subprocess.run(
        ["gh", "secret", "list", "--repo", repo],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set()
    return {line.split("\t", 1)[0] for line in result.stdout.splitlines() if line}


def _set_gh_secret(name: str, value: str, repo: str) -> subprocess.CompletedProcess:
    """Set a single GitHub Actions secret via ``gh secret set``."""
    return subprocess.run(
        ["gh", "secret", "set", name, "--repo", repo, "--body", value],
        capture_output=True,
        text=True,
    )


def _set_gh_secret_from_file(
    name: str, file_path: Path, repo: str
) -> subprocess.CompletedProcess:
    """Set a GitHub Actions secret with the contents of ``file_path``."""
    with open(file_path) as f:
        return subprocess.run(
            ["gh", "secret", "set", name, "--repo", repo],
            stdin=f,
            capture_output=True,
            text=True,
        )


def _key_fingerprint(key_path: Path) -> str:
    """Return ``ssh-keygen -lf`` fingerprint, or empty string on failure."""
    result = subprocess.run(
        ["ssh-keygen", "-lf", str(key_path)],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _project_python_minor(project_root: Path) -> str | None:
    """Extract a major.minor Python version (e.g. ``3.13``) from the project's
    ``pyproject.toml``'s ``requires-python``.

    Returns ``None`` if the file or constraint is missing/unparseable, in
    which case callers should omit the ``uv python install`` step and let
    uv resolve from the lock file.
    """
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return None
    import tomllib

    try:
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    constraint = data.get("project", {}).get("requires-python", "")
    match = re.search(r"(\d+)\.(\d+)", constraint)
    return f"{match.group(1)}.{match.group(2)}" if match else None


def _render_deploy_workflow(on_tag: bool, python_version: str | None = None) -> str:
    """Render the GitHub Actions deploy.yml content.

    Always includes ``workflow_dispatch``. ``on_tag`` additionally fires on
    ``v*`` tag pushes. When ``python_version`` is set, an explicit
    ``uv python install`` step is emitted before ``uv sync`` to pin the
    runtime, mirroring ci.yml.
    """
    triggers = ["  workflow_dispatch:"]
    if on_tag:
        triggers.append("  push:")
        triggers.append("    tags:")
        triggers.append("      - 'v*'")
    on_block = "\n".join(triggers)
    py_step = (
        f"""
    - name: Set up Python
      run: uv python install {python_version}
"""
        if python_version
        else ""
    )
    return f"""name: Deploy

on:
{on_block}

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v6

    - name: Load deploy SSH key
      uses: webfactory/ssh-agent@v0.9.1
      with:
        ssh-private-key: ${{{{ secrets.{_GH_DEPLOY_KEY_SECRET} }}}}

    - name: Trust server host key
      run: ssh-keyscan -H ${{{{ secrets.{_GH_DEPLOY_HOST_SECRET} }}}} >> ~/.ssh/known_hosts

    - name: Install uv
      uses: astral-sh/setup-uv@v7
      with:
        enable-cache: true
        cache-dependency-glob: "uv.lock"
{py_step}
    - name: Install dependencies
      run: uv sync --all-extras

    - name: Deploy
      run: uv run aegis deploy --yes
"""


def deploy_cd_setup_command(
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
    repo: str | None = typer.Option(
        None,
        "--repo",
        help=lazy_t("deploy.help_opt_gh_repo"),
    ),
    on_tag: bool = typer.Option(
        False,
        "--on-tag",
        help=lazy_t("deploy.help_opt_gh_tags"),
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=lazy_t("deploy.help_opt_gh_overwrite"),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=lazy_t("deploy.help_opt_dry_run"),
    ),
    keep_key: str | None = typer.Option(
        None,
        "--keep-key",
        help=lazy_t("deploy.help_opt_local_key_path"),
    ),
) -> None:
    """
    Wire up GitHub Actions continuous deployment for this project.

    Generates a dedicated ed25519 deploy key, installs the public key on
    the deploy server's authorized_keys, pushes the private key + host +
    user to GitHub Actions secrets, and scaffolds .github/workflows/deploy.yml.

    Requires the GitHub CLI (gh) authenticated via 'gh auth login', and an
    .aegis/deploy.yml from a prior 'aegis deploy-init'.

    Examples:\\n
        - aegis deploy-cd-setup\\n
        - aegis deploy-cd-setup --on-tag\\n
        - aegis deploy-cd-setup --force  # rotate existing key\\n
    """
    import os
    import shutil
    import tempfile

    project_root = _get_project_root(project_path)

    # Preflight: gh CLI
    if not dry_run:
        _check_gh_cli()

    # Preflight: deploy config
    config = _load_deploy_config(project_path)
    if not config:
        brand.error(t("deploy.no_config"), err=True)
        raise typer.Exit(1)
    host = config["server"]["host"]
    user = config["server"]["user"]

    # Preflight: repo
    repo_slug = repo or _detect_github_repo(project_root)
    if not repo_slug:
        brand.error(t("deploy.cd_repo_not_detected"), err=True)
        raise typer.Exit(1)

    workflow_path = project_root / ".github" / "workflows" / "deploy.yml"
    marker = f"github-actions-deploy@{repo_slug}"

    # Preflight: collisions
    existing_ci = (
        config.get("ci", {}).get("github") if isinstance(config, dict) else None
    )
    if existing_ci and not force:
        brand.error(
            t(
                "deploy.cd_already_configured",
                fingerprint=existing_ci.get("deploy_key_fingerprint", "unknown"),
            ),
            err=True,
        )
        raise typer.Exit(1)

    if not force and not dry_run:
        existing_secrets = _list_gh_secrets(repo_slug)
        clash = existing_secrets & {
            _GH_DEPLOY_KEY_SECRET,
            _GH_DEPLOY_HOST_SECRET,
            _GH_DEPLOY_USER_SECRET,
        }
        if clash:
            brand.error(
                t("deploy.cd_secret_exists", names=", ".join(sorted(clash))), err=True
            )
            raise typer.Exit(1)

    if workflow_path.exists() and not force:
        brand.error(t("deploy.cd_workflow_exists", path=str(workflow_path)), err=True)
        raise typer.Exit(1)

    # Plan
    brand.accent(
        t("deploy.cd_title", repo=repo_slug, target=f"{user}@{host}"), bold=True
    )
    typer.echo(t("deploy.cd_plan_header"))
    typer.echo(t("deploy.cd_plan_keygen"))
    typer.echo(t("deploy.cd_plan_install", user=user, host=host))
    typer.echo(t("deploy.cd_plan_secrets", repo=repo_slug))
    typer.echo(
        t("deploy.cd_plan_workflow", path=str(workflow_path.relative_to(project_root)))
    )

    if dry_run:
        brand.warn(t("deploy.cd_dry_run"))
        return

    # Generate key
    tempdir = Path(tempfile.mkdtemp(prefix="aegis-deploy-"))
    key_path = tempdir / "aegis_deploy_ci"
    typer.echo(t("deploy.cd_generating_key"))
    keygen = subprocess.run(
        [
            "ssh-keygen",
            "-t",
            "ed25519",
            "-f",
            str(key_path),
            "-N",
            "",
            "-C",
            marker,
            "-q",
        ],
        capture_output=True,
        text=True,
    )
    if keygen.returncode != 0:
        shutil.rmtree(tempdir, ignore_errors=True)
        brand.error(t("deploy.cd_keygen_failed", error=keygen.stderr), err=True)
        raise typer.Exit(1)

    pubkey_body = (key_path.with_suffix(".pub")).read_text().strip()
    fingerprint = _key_fingerprint(key_path.with_suffix(".pub"))

    # If rotating an existing key, remove the previous one first so we don't
    # leave dead keys valid in authorized_keys.
    if force and existing_ci:
        _remove_pubkey_from_server(marker, host, user)

    # Install pubkey on server
    typer.echo(t("deploy.cd_installing_pubkey", user=user, host=host))
    install = _install_pubkey_on_server(pubkey_body, host, user)
    if install.returncode != 0:
        shutil.rmtree(tempdir, ignore_errors=True)
        brand.error(t("deploy.cd_install_failed", error=install.stderr), err=True)
        raise typer.Exit(1)

    # Push secrets
    typer.echo(t("deploy.cd_pushing_secrets", repo=repo_slug))
    secret_calls = [
        (
            _GH_DEPLOY_KEY_SECRET,
            lambda: _set_gh_secret_from_file(
                _GH_DEPLOY_KEY_SECRET, key_path, repo_slug
            ),
        ),
        (
            _GH_DEPLOY_HOST_SECRET,
            lambda: _set_gh_secret(_GH_DEPLOY_HOST_SECRET, host, repo_slug),
        ),
        (
            _GH_DEPLOY_USER_SECRET,
            lambda: _set_gh_secret(_GH_DEPLOY_USER_SECRET, user, repo_slug),
        ),
    ]
    for name, call in secret_calls:
        result = call()
        if result.returncode != 0:
            # Rollback: remove the pubkey we just installed
            _remove_pubkey_from_server(marker, host, user)
            shutil.rmtree(tempdir, ignore_errors=True)
            brand.error(
                t("deploy.cd_secret_failed", name=name, error=result.stderr), err=True
            )
            raise typer.Exit(1)

    # Scaffold workflow
    typer.echo(
        t(
            "deploy.cd_writing_workflow",
            path=str(workflow_path.relative_to(project_root)),
        )
    )
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(
        _render_deploy_workflow(
            on_tag=on_tag,
            python_version=_project_python_minor(project_root),
        )
    )

    # Update .aegis/deploy.yml with ci.github block (merge, don't clobber)
    config.setdefault("ci", {})["github"] = {
        "repo": repo_slug,
        "deploy_key_fingerprint": fingerprint,
        "workflow_path": str(workflow_path.relative_to(project_root)),
    }
    # _save_deploy_config relies on cwd; pass project_path through directly
    config_path = project_root / DEPLOY_CONFIG_FILE
    config_path.parent.mkdir(exist_ok=True)
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)

    # Optional: keep a local copy of the private key
    if keep_key:
        dest = Path(keep_key).expanduser()
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(key_path, dest)
        os.chmod(dest, 0o600)
        typer.echo(t("deploy.cd_kept_key", path=str(dest)))

    # Cleanup tempdir (best-effort secure delete: overwrite then unlink)
    for path in (key_path, key_path.with_suffix(".pub")):
        if path.exists():
            try:
                size = path.stat().st_size
                with open(path, "r+b") as f:
                    f.write(b"\x00" * size)
                    f.flush()
                    os.fsync(f.fileno())
            except OSError:
                pass
    shutil.rmtree(tempdir, ignore_errors=True)

    brand.success(f"\n{t('deploy.cd_complete')}", bold=True)
    typer.echo(t("deploy.cd_fingerprint", fingerprint=fingerprint))
    typer.echo(
        t("deploy.cd_next_commit", path=str(workflow_path.relative_to(project_root)))
    )
    typer.echo(t("deploy.cd_next_run"))
    if not keep_key:
        typer.echo("")
        brand.warn(t("deploy.cd_key_discarded"))
        typer.echo(t("deploy.cd_key_recover_hint"))
