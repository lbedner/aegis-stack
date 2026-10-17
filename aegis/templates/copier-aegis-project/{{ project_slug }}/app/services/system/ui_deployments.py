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

from app.core import exposure, runtime
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
# Everything else done to the server (``deploy_event``), as History lists it.
EVENT_COLUMNS = (
    ("what", "What"),
    ("when", "When"),
    ("by", "By"),
    ("from", "From"),
    ("outcome", "Outcome"),
    ("said", "What happened"),
)


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
    facts = [("Build", build if exposure.deployed() else f"{build}, this machine")]
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


async def offsite() -> dict[str, Any] | None:
    """Backups' off-the-server card: not set up (``state`` "off"), no copy
    yet ("waiting"), or the last copy and the last restore drill (their
    deploy events) as ``facts``, with why the copy failed (``error``).
    None in a stack without the job."""
    try:
        from app.components.deploy.history import latest_event
        from app.components.deploy.protocol import DRILL, EVENT_OK, OFFSITE
        import app.services.system.offsite  # noqa: F401 - the job is in this stack
    except ImportError:
        return None
    from app.core import secrets

    if not await secrets.get("OFFSITE_BACKUP_REPOSITORY"):
        return {"state": "off"}
    copy = await latest_event(OFFSITE)
    if copy is None:
        return {"state": "waiting"}
    drill = await latest_event(DRILL)
    rehearsed = (
        f"{format_relative_time(drill.finished_at)}, "
        + ("passed" if drill.outcome == EVENT_OK else f"failed: {drill.summary}")
        if drill
        else "Never"
    )
    ok = copy.outcome == EVENT_OK
    return {
        "state": "ok" if ok else "failed",
        "error": None if ok else copy.summary,
        "facts": [
            ("Last copy", format_relative_time(copy.finished_at)),
            ("Of", copy.detail.get("stamp", "")),
            ("Copies kept", str(copy.detail["copies"]) if ok else ""),
            (
                "In the bucket",
                format_bytes(held) if ok and (held := copy.detail["bytes"]) else "",
            ),
            ("Restore rehearsed", rehearsed),
        ],
    }


async def history() -> dict[str, Any]:
    """``{"rows": [...], "note": str | None}``: this app's deploy records,
    newest first, or why there are none."""
    try:  # the history ships only with a database (and so SQLAlchemy)
        from sqlalchemy.exc import SQLAlchemyError

        from app.components.deploy.history import recent
    except ImportError:
        return _unread(NO_HISTORY)
    from app.components.deploy.history import recent_events

    try:
        records = await recent()
        events = await recent_events()
    except SQLAlchemyError as exc:  # a build that adds the table, not migrated
        return _unread(f"Deploy history could not be read: {exc}")
    return history_rows(
        [row.model_dump() for row in records], [e.model_dump() for e in events]
    )


def _unread(why: str) -> dict[str, Any]:
    """History's two tables, empty for the one reason both are."""
    return {"rows": [], "note": why, "events": [], "events_note": why}


def live_facts(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """The newest of the History table's ``rows`` (what is live) as facts,
    by its first columns: the build, when, by whom, from where, its health."""
    return [(label, row[k]) for row in rows[:1] for k, label in HISTORY_COLUMNS[:5]]


def history_rows(
    records: list[dict[str, Any]], events: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Deploy records and events (this app's, or the server's ``deploy
    history`` and ``deploy events``) as History's two tables show them."""
    if events:  # only a stack with the deploy component has any
        from app.components.deploy.protocol import EVENT_TITLES
    done = [
        {
            "what": EVENT_TITLES.get(e["kind"], e["kind"]),
            "when": format_relative_time(e["finished_at"]),
            "by": e["actor"] or "",
            "from": e["origin"] or "",
            "outcome": e["outcome"],
            "said": e["summary"],
        }
        for e in events or []
    ]
    rows = []
    for row in records:
        rows.append(
            {
                "build": row["build_id"],
                "started": format_relative_time(row["started_at"]),
                "by": row["deployed_by"] or "",
                "from": row["deployed_from"] or "",
                "health": row["health"] or "",
                "backup": row["backup"] or "",
                "rollback": f"Back to {row['rolled_back_to']}"
                if row["rolled_back_to"]
                else "",
            }
        )
    return {
        "rows": rows,
        "note": None if rows else "No deploys recorded yet.",
        "events": done,
        "events_note": None if done else "Nothing else done to the server yet.",
    }
