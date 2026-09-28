"""Context for the Overseer Worker page's sections.

The Overview leads with the queues: how full each one is (busy slots out of
concurrency times consumers), its share of the backlog and of the finished
work, and how well it is doing, pushed over its own SSE stream while the page
is open. Tasks and Lifecycle are the Flet worker modal's Activity and
Lifecycle tabs, read from the same task history and queue registry.
"""

from collections import deque
import time
from typing import Any

from app.core.formatting import (
    format_duration_ms,
    format_relative_time,
    format_span,
    format_timestamp,
)
from app.core.log import logger
from app.services.system import ui_worker
from app.services.system.models import ComponentStatus, ComponentStatusType

from .filters import color_tone
from .overseer_live import fragment_events
from .overseer_nav import SectionRequest
from .rendering import page_number, pager, status_cell, templates, with_query

SECTIONS = (
    (None, {"overview": "Overview"}),
    ("Activity", {"tasks": "Tasks"}),
    ("Configuration", {"runtime": "Runtime", "lifecycle": "Lifecycle"}),
)

QUEUES_EVENTS = "/overseer/events/worker-queues"
QUEUES_EVENT = "worker-queues"
QUEUES_TEMPLATE = "pages/overseer/worker/_queues.html"
QUEUES_INTERVAL_SECONDS = 3.0
# The live view's memory: ~5 minutes of samples per queue at the interval.
TREND_SAMPLES = 100
PILE_CELLS = 40
SPARK_WIDTH, SPARK_HEIGHT = 240, 28
PAGE_SIZE = 25
STATUS_FILTERS = {"all": "All"} | {
    key: label for key, (label, _) in ui_worker.TASK_STATUSES.items()
}


async def load_worker() -> ComponentStatus:
    """A fresh read of every queue, from the worker health check."""
    try:
        from app.services.system.health_worker import check_worker_health
    except ImportError:
        return ComponentStatus(name="worker", message="No worker installed")
    return await check_worker_health()


async def load_tasks(
    *,
    queue: str | None,
    queues: list[str],
    status: str | None,
    offset: int,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """A page of task records, newest first, from one queue or all of them.

    Across queues each is read up to this page's end and the lists merged,
    so page N reads N pages per queue at most.
    """
    import redis.asyncio as aioredis

    from app.components.worker.task_history import list_tasks_by_queue
    from app.services.system.redis_keys import redis_url

    names = [queue] if queue else queues
    client = aioredis.from_url(redis_url(), decode_responses=True)
    try:
        found: list[dict[str, Any]] = []
        total = 0
        for name in names:
            tasks, count = await list_tasks_by_queue(
                client, name, 0, offset + limit, "desc", status=status
            )
            found += tasks
            total += count
    finally:
        await client.aclose()
    found.sort(key=lambda t: t.get("enqueued_at") or "", reverse=True)
    return found[offset : offset + limit], total


def _hook_row(hook: dict[str, str], role: str) -> dict[str, Any]:
    details = {"Description": hook.get("description"), "Module": hook.get("module")}
    return {
        "name": hook.get("name"),
        "role": status_cell(role, "accent" if role == "Hook" else "muted"),
        "module": hook.get("module"),
        "details": {k: v for k, v in details.items() if v},
    }


def load_lifecycle(queue: str) -> dict[str, list[dict[str, Any]]]:
    """One queue's startup hook, its job hooks and tasks, and its shutdown."""
    from app.components.worker.registry import (
        get_queue_lifecycle,
        get_queue_metadata,
        get_task_docstrings,
    )

    hooks = get_queue_lifecycle(queue)
    docs = get_task_docstrings(queue)
    tasks = [
        _hook_row({"name": name} | docs.get(name, {}), "Task")
        for name in get_queue_metadata(queue).get("functions", [])
    ]

    def hook(key: str) -> list[dict[str, Any]]:
        return [_hook_row(hooks[key], "Hook")] if hooks.get(key) else []

    return {
        "startup": hook("on_startup"),
        "jobs": hook("on_job_start") + tasks + hook("after_job_end"),
        "shutdown": hook("on_shutdown"),
    }


async def load_runtime() -> list[dict[str, str]]:
    """What each live worker process reports it is running with."""
    try:
        from app.components.worker.runtime import read_runtime
    except ImportError:
        return []
    import redis.asyncio as aioredis

    from app.services.system.redis_keys import redis_url

    client = aioredis.from_url(redis_url())
    try:
        return await read_runtime(client)
    finally:
        await client.aclose()


def misnamed_queues() -> list[str]:
    """Names in ``Settings.WORKER_QUEUES`` that match no queue: a worker
    refuses to start on them, and this page says which."""
    try:
        from app.components.worker.registry import discover_worker_queues
        from app.components.worker.runtime import unknown_queues
        from app.core.config import settings
    except ImportError:
        return []
    return unknown_queues(settings.WORKER_QUEUES, discover_worker_queues())


def _held(reports: list[dict[str, str]]) -> dict[str, int]:
    """Jobs each queue's reporting processes may hold, summed."""
    held: dict[str, int] = {}
    for r in reports:
        if r.get("concurrency", "").isdigit():
            held[r["queue"]] = held.get(r["queue"], 0) + int(r["concurrency"])
    return held


async def queues_view(worker: ComponentStatus | None = None) -> dict[str, Any]:
    """The queues and totals for ``_queues.html``."""
    reports = await load_runtime()
    worker = worker or await load_worker()
    view = ui_worker.overview(worker, held=_held(reports))
    # With no queues to show, an unhealthy worker's message is the page.
    unhealthy = worker.status == ComponentStatusType.UNHEALTHY
    view["problem"] = worker.message if unhealthy and not view["queues"] else None
    for q in view["queues"]:
        q["tone"] = color_tone(q["color"])
        q["success_tone"] = color_tone(q["success_color"])
        q["pile"] = ui_worker.pile(q["queued"], PILE_CELLS)
        q["oldest"] = format_span(q["oldest_waiting"]) if q["queued"] else None
    return view


def add_trends(
    view: dict[str, Any], history: dict[str, deque[ui_worker.Sample]], now: float
) -> dict[str, Any]:
    """Record this reading in ``history`` and give each queue its rate, when
    its backlog drains, and a line of its waiting jobs over time."""
    for q in view["queues"]:
        samples = history.setdefault(q["name"], deque(maxlen=TREND_SAMPLES))
        samples.append((now, q["queued"], q["completed"] + q["failed"]))
        per_second = ui_worker.rate(list(samples))
        net = ui_worker.net_rate(list(samples))
        q["rate"] = per_second
        q["drain"] = ui_worker.drain(q["queued"], per_second, net)
        q["spark"] = ui_worker.sparkline(
            [waiting for _, waiting, _ in samples], SPARK_WIDTH, SPARK_HEIGHT
        )
    return view


def render_queues(view: dict[str, Any]) -> str:
    return templates.env.get_template(QUEUES_TEMPLATE).render(worker=view)


def queues_events(max_frames: int | None = None):  # noqa: ANN201 - async iterator
    """The queues over SSE, sent again only when they change."""

    history: dict[str, deque[ui_worker.Sample]] = {}

    async def render() -> str:
        try:
            view = await queues_view()
            return render_queues(add_trends(view, history, time.monotonic()))
        except Exception as exc:  # noqa: BLE001 - keep the stream, show nothing new
            logger.warning("Worker queue read failed", error=str(exc))
            return ""

    return fragment_events(QUEUES_EVENT, render, QUEUES_INTERVAL_SECONDS, max_frames)


def _task_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for r in records:
        label, color = ui_worker.task_status(r.get("status", "unknown"))
        duration = r.get("duration_ms")
        rows.append(
            {
                "name": r.get("name") or "unknown",
                "queue": r.get("queue"),
                "duration": format_duration_ms(float(duration)) if duration else None,
                "enqueued": format_relative_time(r.get("enqueued_at")),
                "state": status_cell(label, color_tone(color)),
                "error": r.get("error") if r.get("status") == "failed" else None,
                "description": r.get("description"),
                "job_id": r.get("job_id"),
                "started": format_timestamp(r.get("started_at")),
                "finished": format_timestamp(r.get("finished_at")),
            }
        )
    return rows


async def _tasks(req: SectionRequest) -> dict[str, Any]:
    names = [q["name"] for q in (await queues_view())["queues"]]
    queue = req.query.get("queue") if req.query.get("queue") in names else None
    status = (
        req.query.get("status") if req.query.get("status") in STATUS_FILTERS else None
    )
    status = None if status == "all" else status
    page = page_number(req.query.get("page"))
    records, total = await load_tasks(
        queue=queue,
        queues=names,
        status=status,
        offset=(page - 1) * PAGE_SIZE,
        limit=PAGE_SIZE,
    )
    path = req.path
    return {
        "tasks": _task_rows(records),
        "queue_filters": [
            (
                label,
                key == (queue or "all"),
                with_query(path, queue=None if key == "all" else key, status=status),
            )
            for key, label in [("all", "All queues"), *((n, n) for n in names)]
        ],
        "status_filters": [
            (
                label,
                key == (status or "all"),
                with_query(path, queue=queue, status=None if key == "all" else key),
            )
            for key, label in STATUS_FILTERS.items()
        ],
        "here": with_query(path, queue=queue, status=status),
        "pager": pager(
            path,
            page,
            PAGE_SIZE,
            total,
            **{k: v for k, v in {"queue": queue, "status": status}.items() if v},
        ),
    }


def _runtime_card(report: dict[str, str]) -> dict[str, Any]:
    running, asked = report.get("concurrency"), report.get("configured")
    source = report.get("source", "")
    engine = " ".join(x for x in (report.get("engine"), report.get("version")) if x)
    return {
        "worker": report.get("worker"),
        "queue": report.get("queue"),
        "facts": [
            ("Engine", engine),
            ("Queue", report.get("queue")),
            ("Processes", report.get("processes")),
            ("At once", f"{running} per process" if running else None),
            ("From", source),
        ],
        "mismatch": (
            f"Running {running} per process; {source} asks for {asked}. "
            "Started outside the entrypoint, or before the setting changed: "
            "restart it."
            if running and asked and running != asked
            else None
        ),
    }


async def _runtime() -> dict[str, Any]:
    return {
        "runtime": [_runtime_card(r) for r in await load_runtime()],
        "misnamed": misnamed_queues(),
    }


async def _lifecycle(req: SectionRequest) -> dict[str, Any]:
    names = [q["name"] for q in (await queues_view())["queues"]]
    queue = req.query.get("queue") if req.query.get("queue") in names else None
    queue = queue or (names[0] if names else None)
    return {
        "queue": queue,
        "queue_links": [(n, n == queue, with_query(req.path, queue=n)) for n in names],
        "lifecycle": load_lifecycle(queue) if queue else None,
    }


async def section_context(
    section: str, worker: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """What the named section's template needs beyond the worker status."""
    if section == "overview":
        return {
            # The header renders once; every number lives in the live stream.
            "header_message": None,
            "worker": add_trends(await queues_view(), {}, time.monotonic()),
            "queues_events": QUEUES_EVENTS,
            "queues_event": QUEUES_EVENT,
        }
    if section == "tasks":
        return await _tasks(req)
    if section == "runtime":
        return await _runtime()
    if section == "lifecycle":
        return await _lifecycle(req)
    return {}
