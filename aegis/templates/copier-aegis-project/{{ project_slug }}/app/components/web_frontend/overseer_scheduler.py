"""Context for the Overseer Scheduler page's sections.

The Flet scheduler modal's Jobs and History. Overview and Jobs read the
scheduler health check (every task, not a sample); History reads the same
execution log the API serves, through the API's own handler.
"""

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.formatting import (
    format_duration_ms,
    format_relative_time,
    format_schedule_human_readable,
    format_timestamp,
)
from app.services.system import ui_scheduler
from app.services.system.models import ComponentStatus

from .filters import color_tone
from .overseer_access import Db
from .overseer_nav import SectionRequest, page_url
from .rendering import page_number, pager, status_cell, with_query

SECTIONS = (
    (None, {"overview": "Overview"}),
    ("Activity", {"jobs": "Jobs", "history": "History"}),
)

# Where this page's dialogs live (``routes/partials/overseer_scheduler``).
PARTIALS = "/partials/overseer/scheduler"
PAGE_SIZE = 25
STATUS_FILTERS = {
    "all": "All",
    **{k: v[0] for k, v in ui_scheduler.EXECUTION_STATUSES.items()},
}


def task_manager() -> Any | None:
    """The scheduler's task manager, or None without persistence.

    The manager (and the job store and history it reads) is only generated
    with a persistent backend (sqlite or postgres). Imported here, not at the
    top: the scheduler only exists in stacks that have it.
    """
    try:
        from app.services.scheduler import ScheduledTaskManager
    except ImportError:
        return None
    return ScheduledTaskManager()


def persistent() -> bool:
    """Whether this scheduler keeps its jobs and history in the database."""
    return task_manager() is not None


async def load_executions(
    *,
    db: Db,
    offset: int,
    limit: int,
    status: str | None,
    job_id: str | None,
) -> tuple[list[dict[str, Any]], int]:
    """A page of execution history, newest first, and how many match.

    Reads on the request's own session (``db``). Rows are shaped by the
    API's own response model.
    """
    from app.components.backend.api.models import JobExecutionRead

    records, total = await task_manager().list_executions(
        offset=offset, limit=limit, status=status, job_id=job_id, session=db
    )
    rows = [JobExecutionRead.model_validate(r).model_dump(mode="json") for r in records]
    return rows, total


async def load_job_stats(*, db: Db, job_ids: list[str]) -> dict[str, Any]:
    """Each job's run stats from the execution history, in one query, on the
    request's own session."""
    return await task_manager().get_jobs_stats(job_ids, session=db)


def store_label() -> str:
    """The hub's second line: where the scheduler keeps its jobs."""
    if not persistent():
        return "Memory store"
    url = getattr(settings, "database_url_effective", None) or settings.DATABASE_URL
    engine = str(url).split(":", 1)[0].split("+", 1)[0]
    return {"postgresql": "Postgres store", "sqlite": "SQLite store"}.get(
        engine, f"{engine} store"
    )


def tasks(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """Every scheduled job the health check reported, soonest first."""
    return list(metadata.get("upcoming_tasks") or [])


def _run_stats(stats: dict[str, Any] | None) -> list[tuple[str, str]]:
    """A job's run stats as ``stat_row`` items; empty before its first run."""
    if not stats or not stats.get("total_runs"):
        return []
    last = stats.get("last_run") or {}
    label, _color = ui_scheduler.execution_status(last.get("status", "unknown"))
    return [
        ("Runs", str(stats["total_runs"])),
        ("Success", f"{stats.get('success_rate', 0)}%"),
        ("Average", format_duration_ms(stats.get("avg_duration_ms"))),
        ("Last run", f"{label}, {format_relative_time(last.get('started_at'))}"),
    ]


async def _stats_for(req: SectionRequest, jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Each job's run stats, in one query; none without persistence."""
    if not persistent():
        return {}
    return await load_job_stats(db=req.db, job_ids=[str(t.get("job_id")) for t in jobs])


def _job_rows(
    metadata: dict[str, Any], stats: dict[str, Any], history: str
) -> list[dict[str, Any]]:
    rows = []
    for task in tasks(metadata):
        next_run, label, color = ui_scheduler.job_state(
            task.get("status", "active"), task.get("next_run", "")
        )
        rows.append(
            {
                "id": task.get("job_id"),
                "name": task.get("name") or task.get("job_id"),
                "next_run": next_run,
                "schedule": format_schedule_human_readable(task.get("schedule", "")),
                "state": status_cell(label, color_tone(color)),
                "function": task.get("function"),
                "description": task.get("description"),
                "stats": _run_stats(stats.get(task.get("job_id"))),
                "history": with_query(history, job=task.get("job_id")),
            }
        )
    return rows


def _execution_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        label, color = ui_scheduler.execution_status(record.get("status", "unknown"))
        rows.append(
            {
                "job": record.get("job_name") or record.get("job_id", "unknown"),
                "duration": format_duration_ms(record.get("duration_ms")),
                "started": format_relative_time(record.get("started_at")),
                "state": status_cell(label, color_tone(color)),
                "error": record.get("error_message")
                if record.get("status") == "failed"
                else None,
                "job_id": record.get("job_id"),
                "scheduled": format_timestamp(record.get("scheduled_run_time")),
                "finished": format_timestamp(record.get("finished_at")),
            }
        )
    return rows


async def _history(req: SectionRequest, metadata: dict[str, Any]) -> dict[str, Any]:
    path, query = req.path, req.query
    status = query.get("status", "all")
    status = status if status in STATUS_FILTERS else "all"
    status_param = None if status == "all" else status
    job = query.get("job") or None
    page = page_number(query.get("page"))
    if not persistent():
        return {"history_available": False}
    records, total = await load_executions(
        db=req.db,
        offset=(page - 1) * PAGE_SIZE,
        limit=PAGE_SIZE,
        status=status_param,
        job_id=job,
    )
    names = {t.get("job_id"): t.get("name") for t in tasks(metadata)}
    params = {k: v for k, v in {"status": status_param, "job": job}.items() if v}
    return {
        "history_available": True,
        "executions": _execution_rows(records),
        "status": status,
        "filters": {
            key: (
                label,
                with_query(path, status=None if key == "all" else key, job=job),
            )
            for key, label in STATUS_FILTERS.items()
        },
        "here": with_query(path, **params),
        "job": {
            "name": names.get(job) or job,
            "clear_url": with_query(path, status=status_param),
        }
        if job
        else None,
        "pager": pager(path, page, PAGE_SIZE, total, **params),
    }


async def section_context(
    section: str, scheduler: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """What the named section's template needs beyond the scheduler status."""
    metadata = scheduler.metadata or {}
    if section == "overview":
        jobs = tasks(metadata)
        stats = await _stats_for(req, jobs)
        tz = ZoneInfo(settings.SCHEDULER_TIMEZONE)
        return {
            "clock": ui_scheduler.clock(jobs, datetime.now(UTC), tz, stats=stats),
            "store": store_label(),
        }
    if section == "jobs":
        stats = await _stats_for(req, tasks(metadata))
        history = page_url("components", "scheduler") + "/history"
        return {"jobs": _job_rows(metadata, stats, history), "partials": PARTIALS}
    if section == "history":
        return await _history(req, metadata)
    return {}
