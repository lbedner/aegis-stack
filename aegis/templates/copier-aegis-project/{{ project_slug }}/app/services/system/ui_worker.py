"""What the worker detail views show, for every frontend.

Built from the worker health check: each queue's state, how full it is (busy
slots out of concurrency times consumers), and its share of the backlog and
of the finished work. Colours are semantic names (green, blue, yellow, red,
grey), which each frontend maps to its own theme.
"""

import asyncio
import math
from typing import Any, NamedTuple

from app.core import series
from app.core.constants import ComponentName
from app.services.system.models import ComponentStatus, ComponentStatusType

SUCCESS_RATE_HEALTHY = 95  # % - green
SUCCESS_RATE_WARNING = 80  # % - yellow

TASK_STATUSES: dict[str, tuple[str, str]] = {
    "completed": ("Completed", "green"),
    "failed": ("Failed", "red"),
    "running": ("Running", "blue"),
    "enqueued": ("Enqueued", "grey"),
}


def task_status(status: str) -> tuple[str, str]:
    """A task record's status: its label and colour."""
    return TASK_STATUSES.get(status, (status.replace("_", " ").capitalize(), "grey"))


BACKED_UP = "backed_up"  # the verdict state of a queue backing up
# Each verdict state as a label and colour; a healthy queue that is busy
# reads "Active" instead of "Online".
STATE_LABELS: dict[str, tuple[str, str]] = {
    "no_tasks": ("No tasks", "grey"),
    "offline": ("Offline", "red"),
    "failing": ("Failing", "red"),
    "degraded": ("Degraded", "yellow"),
    BACKED_UP: ("Backed up", "yellow"),
    "healthy": ("Online", "green"),
}


def _verdict(queue: ComponentStatus) -> Any:
    """The health check's own rule, applied to the queue's figures, so the
    views and the health check can never disagree."""
    from app.services.system.health_worker_rules import queue_verdict

    meta = queue.metadata or {}
    return queue_verdict(
        worker_alive=bool(meta.get("worker_alive", False)),
        has_functions="no functions" not in (queue.message or "").lower(),
        waiting=int(meta.get("queued_jobs", 0) or 0),
        failure_rate=float(meta.get("failure_rate_percent", 0.0) or 0.0),
        oldest_waiting=meta.get("oldest_waiting_seconds"),
        max_wait=meta.get("max_wait_seconds"),
    )


def queue_state(queue: ComponentStatus) -> tuple[str, str]:
    """A queue's state in a word, and its colour."""
    verdict = _verdict(queue)
    if verdict.state == "healthy" and (queue.metadata or {}).get("jobs_ongoing", 0):
        return "Active", "yellow"
    return STATE_LABELS[verdict.state]


def success_color(rate: float | None) -> str:
    """Green from 95%, yellow from 80%, red below; grey with no history."""
    if rate is None:
        return "grey"
    if rate >= SUCCESS_RATE_HEALTHY:
        return "green"
    return "yellow" if rate >= SUCCESS_RATE_WARNING else "red"


def _pct(part: float, whole: float) -> int:
    return min(100, round(part / whole * 100)) if whole else 0


def _success(completed: int, failed: int) -> float | None:
    finished = completed + failed
    return round(completed / finished * 100, 1) if finished else None


def queue_view(
    queue: ComponentStatus, procs: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """One queue: state, fullness and outcomes.

    ``procs`` are its reporting processes (``processes``): their slots and
    running jobs, live. Without reports, the configured limit times the
    consumers and the task history's running count stand in.
    """
    meta = queue.metadata or {}
    label, color = queue_state(queue)
    verdict = _verdict(queue)
    consumers = int(meta.get("consumer_count", 0) or 0)
    configured = int(meta.get("max_concurrency", 0) or 0) * max(consumers, 1)
    slots = sum(p["slots"] for p in procs or []) or configured
    busy = (
        sum(p["busy"] for p in procs)
        if procs
        else int(meta.get("jobs_ongoing", 0) or 0)
    )
    completed = int(meta.get("jobs_completed", 0) or 0)
    failed = int(meta.get("jobs_failed", 0) or 0)
    success = _success(completed, failed) if meta.get("worker_alive") else None
    return {
        "name": queue.name,
        "description": meta.get("description", ""),
        "state": label,
        "color": color,
        "queued": int(meta.get("queued_jobs", 0) or 0),
        "busy": busy,
        "slots": slots,
        "busy_pct": _pct(busy, slots),
        "completed": completed,
        "failed": failed,
        "success": success,
        "success_color": success_color(success),
        "consumers": consumers,
        "timeout": meta.get("timeout_seconds"),
        "stream": meta.get("stream_name"),
        "processes": procs or [],
        "oldest_waiting": meta.get("oldest_waiting_seconds"),
        "detail": verdict.lead if label != "No tasks" else "",
        "verdict": verdict.state,
    }


class Backlog(NamedTuple):
    """The worker's queues as one part (Overseer's queue node): what waits
    and what runs now; healthy, or warning while any queue backs up."""

    status: ComponentStatusType
    message: str
    queued: int


def backlog(worker: ComponentStatus) -> Backlog:
    """The worker's queues as one ``Backlog``, by the health check's own rule."""
    found = overview(worker)
    queued = found["queued"]
    message = f"{queued} queued, {found['busy']} running"
    lags = [q["detail"] for q in found["queues"] if q["verdict"] == BACKED_UP]
    if lags:
        return Backlog(ComponentStatusType.WARNING, f"{message}: {lags[0]}", queued)
    return Backlog(ComponentStatusType.HEALTHY, message, queued)


def overview(
    worker: ComponentStatus, procs: dict[str, list[dict[str, Any]]] | None = None
) -> dict[str, Any]:
    """Every queue, with its share of the backlog and of the finished work,
    and the worker's totals; ``procs``: each queue's processes."""
    group = worker.sub_components.get("queues")
    queues = [
        queue_view(q, (procs or {}).get(name))
        for name, q in (group.sub_components if group else {}).items()
    ]
    queued = sum(q["queued"] for q in queues)
    finished = sum(q["completed"] + q["failed"] for q in queues)
    for q in queues:
        q["backlog_share"] = _pct(q["queued"], queued)
        q["work_share"] = _pct(q["completed"] + q["failed"], finished)
    busy, slots = sum(q["busy"] for q in queues), sum(q["slots"] for q in queues)
    completed = sum(q["completed"] for q in queues)
    success = _success(completed, finished - completed)
    return {
        "queues": queues,
        "queued": queued,
        "busy": busy,
        "slots": slots,
        "busy_pct": _pct(busy, slots),
        "completed": completed,
        "failed": finished - completed,
        "success": success,
        "success_color": success_color(success),
    }


def pile(count: int, cells: int = 40) -> dict[str, int]:
    """Waiting jobs as blocks: ``lit`` of ``cells``, ``per_block`` jobs each
    (one per job while they fit)."""
    per_block = max(1, math.ceil(count / cells))
    return {"lit": math.ceil(count / per_block), "per_block": per_block}


# A queue's trend, one point a reading: (seconds, waiting, done).
TrendPoint = tuple[float, int, int]
RATE_WINDOW_SECONDS = 30.0
MIN_RATE_SPAN_SECONDS = 2.0
# A net rate this close to zero is keeping pace, not draining or growing.
STEADY_NET_RATE = 0.2
STEADY_SHARE = 0.1


def rate(
    samples: list[TrendPoint], window: float = RATE_WINDOW_SECONDS
) -> float | None:
    """Jobs finished per second over the last ``window`` seconds, or None
    until the samples span long enough to say."""
    if not samples:
        return None
    recent = [s for s in samples if s[0] >= samples[-1][0] - window]
    span = recent[-1][0] - recent[0][0]
    if span < MIN_RATE_SPAN_SECONDS:
        return None
    return round(max(0, recent[-1][2] - recent[0][2]) / span, 1)


def net_rate(
    samples: list[TrendPoint], window: float = RATE_WINDOW_SECONDS
) -> float | None:
    """How fast the backlog shrinks, in jobs per second: finishing minus
    arriving, read as the change in waiting. Negative while it grows."""
    if not samples:
        return None
    recent = [s for s in samples if s[0] >= samples[-1][0] - window]
    span = recent[-1][0] - recent[0][0]
    if span < MIN_RATE_SPAN_SECONDS:
        return None
    return round((recent[0][1] - recent[-1][1]) / span, 1)


def drain(waiting: int, per_second: float | None, net: float | None) -> str:
    """Where the backlog is heading, in words.

    From the net rate, not the finishing rate: jobs arriving as fast as
    they finish never drain, however quick each one is.
    """
    if not waiting:
        return "caught up"
    if per_second is None or net is None:
        return "measuring"
    if per_second <= 0:
        return "stalled, nothing finishing"
    if abs(net) < max(STEADY_NET_RATE, per_second * STEADY_SHARE):
        return "steady, keeping pace"
    if net < 0:
        return f"growing by ~{abs(net)} jobs/s"
    seconds = waiting / net
    if seconds < 60:
        return f"drains in ~{max(1, round(seconds))}s"
    return f"drains in ~{round(seconds / 60)} min"


# The queues as a sampler (``app.core.series``): the worker health check and
# each worker process's report, read once a tick for every viewer, and each
# queue's waiting and finished counts kept, so a view's trend is the same for
# everyone and survives a reconnect.
QUEUES_SAMPLER = "worker-queues"
TREND_SECONDS = 300  # how far back a queue's trend reads


async def load_worker() -> ComponentStatus:
    """A fresh read of every queue, from the worker health check."""
    try:
        from app.services.system.health_worker import check_worker_health
    except ImportError:
        return ComponentStatus(name=ComponentName.WORKER, message="No worker installed")
    return await check_worker_health()


async def load_runtime() -> list[dict[str, str]]:
    """What each live worker process reports it is running with, and how
    many jobs it is running now."""
    try:
        from app.components.worker.heartbeat import with_busy
        from app.components.worker.runtime import read_runtime
    except ImportError:
        return []
    from app.services.system.redis_keys import redis_client

    client = redis_client()
    try:
        return await with_busy(client, await read_runtime(client))
    finally:
        await client.aclose()


def processes(reports: list[dict[str, str]]) -> dict[str, list[dict[str, Any]]]:
    """Each queue's reporting processes: the slots each may fill and the jobs
    it is running now."""
    found: dict[str, list[dict[str, Any]]] = {}
    for r in reports:
        if r.get("concurrency", "").isdigit() and int(r["concurrency"]):
            found.setdefault(r.get("queue", ""), []).append(
                {
                    "worker": r.get("worker", ""),
                    "slots": int(r["concurrency"]),
                    "busy": int(r.get("busy") or 0),
                }
            )
    return found


async def read_queues() -> series.Sample:
    """One reading: ``latest`` is the worker and its processes' reports."""
    worker, reports = await asyncio.gather(load_worker(), load_runtime())
    values: dict[str, float] = {}
    for q in overview(worker)["queues"]:
        values[f"{q['name']}:queued"] = q["queued"]
        values[f"{q['name']}:done"] = q["completed"] + q["failed"]
    return series.Sample(values, (worker, reports))


# Unwatched, once a minute: enough for a trend to have points when a page
# opens, without reading Redis every 15 seconds for nobody.
QUEUES = series.Sampler(QUEUES_SAMPLER, read_queues, interval=3.0, idle_interval=60.0)


def samples(
    found: dict[str, list[tuple[float, float]]], queue: str
) -> list[TrendPoint]:
    """A queue's kept series (``series.read``) as trend samples."""
    done = dict(found.get(f"{queue}:done", []))
    return [
        (at, int(waiting), int(done[at]))
        for at, waiting in found.get(f"{queue}:queued", [])
        if at in done
    ]
