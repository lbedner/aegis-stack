"""What is deployed, as Overseer shows it in htmx and Flet alike.

``now()`` is the live build (``settings.BUILD_ID``, which ``aegis deploy``
stamps with the short commit), its commit and when the server went live
(its instance's start, from ``app.core.runtime``), and the last health
check. ``host()`` is the machine it runs on (``runtime.host()``: through
the socket proxy on a deployed server, this process's machine otherwise).
``backups()`` lists the scheduled database backups on the backup volume,
and ``history()`` the deploy records (``app.components.deploy.history``),
with who deployed the live build on Now; both need the deploy component and
a database. No UI framework imports.
"""

from datetime import UTC, datetime
import re
from typing import Any

from app.core import runtime
from app.core.config import settings
from app.core.formatting import (
    format_bytes,
    format_date,
    format_percentage,
    format_relative_time,
)
from app.core.log import logger
from app.core.runtime import RuntimeUnavailableError
from app.services.system import health

LOCAL = "dev"  # BUILD_ID before any deploy stamps it
# What ``aegis deploy`` stamps: a short commit, and for a tree with
# uncommitted changes, ``-dirty-<unix time>`` after it.
_BUILD = re.compile(r"^(?P<commit>[0-9a-f]{7,40})(?P<dirty>-dirty-\d+)?$")
SERVER = "webserver"  # the compose service whose start is "live since"
BACKUP_COLUMNS = (("name", "Backup"), ("size", "Size"), ("taken", "Taken"))
HISTORY_COLUMNS = (
    ("build", "Build"),
    ("started", "Went live"),
    ("by", "Deployed by"),
    ("from", "From"),
    ("health", "Health"),
    ("backup", "Backup taken"),
    ("rollback", "Rollback"),
)
NO_HISTORY = "Deploy history needs the deploy component and a database."


def commit() -> str | None:
    """The live build's commit, saying so when it had uncommitted changes;
    None for a build no deploy stamped."""
    if found := _BUILD.match(settings.BUILD_ID):
        return found["commit"] + (
            ", with uncommitted changes" if found["dirty"] else ""
        )
    return None


async def now() -> list[tuple[str, str]]:
    """The live build as ``(label, value)`` facts."""
    build = settings.BUILD_ID
    facts = [("Build", f"{build}, not deployed" if build == LOCAL else build)]
    if live := commit():
        facts.append(("Commit", live))
    if by := await _deployed_by(build):
        facts.append(("Deployed by", by))
    if started := await _live_since():
        when = f"{format_date(started)} {started:%H:%M} UTC"
        facts.append(("Live since", f"{when} ({format_relative_time(started)})"))
    facts.append(("Health", _health()))
    return facts


async def _live_since() -> datetime | None:
    """When the server's (first) instance started, if the runtime says."""
    try:
        services = await runtime.services()
    except RuntimeUnavailableError:
        return None
    starts = [
        i.started_at
        for s in services
        if s.name == SERVER
        for i in s.instances
        if i.started_at
    ]
    return min(starts).replace(tzinfo=UTC) if starts else None


async def _deployed_by(build: str) -> str | None:
    """Who deployed the live build, and from where, if a record says."""
    try:  # the history ships only with a database (and so SQLAlchemy)
        from sqlalchemy.exc import SQLAlchemyError

        from app.components.deploy.history import get
    except ImportError:  # no deploy history in this stack
        return None
    try:
        row = await get(build)
    except SQLAlchemyError as exc:  # not migrated yet: Now still shows
        logger.warning("deploy.history_unreadable", error=str(exc))
        return None
    if row is None or not row.deployed_by:
        return None
    return (
        f"{row.deployed_by} from {row.deployed_from}"
        if row.deployed_from
        else row.deployed_by
    )


def _health() -> str:
    status = health.last_system_status()
    if status is None:
        return "Not checked yet"
    return "Healthy" if status.overall_healthy else "Needs attention"


async def host() -> dict[str, Any]:
    """``{"facts": [(label, value)], "note": str | None}`` for the host."""
    try:
        found = await runtime.host()
    except RuntimeUnavailableError as exc:
        return {"facts": [], "note": f"The runtime did not answer: {exc}"}
    used = found.disk_total - found.disk_free
    share = used / found.disk_total * 100 if found.disk_total else 0.0
    facts = [
        ("CPUs", str(found.cpus)),
        ("Memory", format_bytes(found.memory)),
        (
            "Disk",
            f"{format_bytes(used)} of {format_bytes(found.disk_total)} used"
            f" ({format_percentage(share)})",
        ),
    ]
    if found.docker_version:
        facts.append(("Docker", found.docker_version))
    return {"facts": facts, "note": None}


def backups() -> dict[str, Any]:
    """``{"rows": [...], "note": str | None}``: the database backups,
    newest first, or why there are none."""
    try:
        from app.services.system.backup import backup_dir, list_backups
    except ImportError:  # no scheduled database backups in this stack
        return {"rows": [], "note": "This stack takes no scheduled database backups."}
    directory = backup_dir()
    files = list_backups(directory) if directory.is_dir() else []
    if not files:
        return {"rows": [], "note": f"No backups yet; they are written to {directory}."}
    rows = []
    for path in files:
        stat = path.stat()
        taken = datetime.fromtimestamp(stat.st_mtime, UTC)
        rows.append(
            {
                "name": path.name,
                "size": format_bytes(stat.st_size),
                "taken": format_relative_time(taken),
            }
        )
    return {"rows": rows, "note": None}


async def history() -> dict[str, Any]:
    """``{"rows": [...], "note": str | None}``: the deploy records, newest
    first, or why there are none."""
    try:  # the history ships only with a database (and so SQLAlchemy)
        from sqlalchemy.exc import SQLAlchemyError

        from app.components.deploy.history import recent
    except ImportError:
        return {"rows": [], "note": NO_HISTORY}
    try:
        records = await recent()
    except SQLAlchemyError as exc:  # a build that adds the table, not migrated
        return {"rows": [], "note": f"Deploy history could not be read: {exc}"}
    rows = [
        {
            "build": row.build_id,
            "started": format_relative_time(row.started_at.replace(tzinfo=UTC)),
            "by": row.deployed_by or "",
            "from": row.deployed_from or "",
            "health": row.health or "",
            "backup": row.backup or "",
            "rollback": f"Back to {row.rolled_back_to}" if row.rolled_back_to else "",
        }
        for row in records
    ]
    if not rows:
        return {"rows": [], "note": "No deploys recorded yet."}
    return {"rows": rows, "note": None}
