"""What the worker detail views show, for every frontend.

Built from the worker health check: each queue's state, how full it is (busy
slots out of concurrency times consumers), and its share of the backlog and
of the finished work. Colours are semantic names (green, blue, yellow, red,
grey), which each frontend maps to its own theme.
"""

import asyncio
import math
from typing import Any

from app.core import series
from app.services.system.models import ComponentStatus

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


# Each verdict state as a label and colour; a healthy queue that is busy
# reads "Active" instead of "Online".
STATE_LABELS: dict[str, tuple[str, str]] = {
    "no_tasks": ("No tasks", "grey"),
    "offline": ("Offline", "red"),
    "failing": ("Failing", "red"),
    "degraded": ("Degraded", "yellow"),
    "backed_up": ("Backed up", "yellow"),
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


def queue_view(queue: ComponentStatus, held: int | None = None) -> dict[str, Any]:
    """One queue: state, fullness and outcomes.

    ``held`` is how many jobs its workers report they may hold at once;
    without a report the configured limit times the consumers stands in.
    """
    meta = queue.metadata or {}
    label, color = queue_state(queue)
    consumers = int(meta.get("consumer_count", 0) or 0)
    configured = int(meta.get("max_concurrency", 0) or 0) * max(consumers, 1)
    slots = held or configured
    busy = int(meta.get("jobs_ongoing", 0) or 0)
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
        "oldest_waiting": meta.get("oldest_waiting_seconds"),
        "detail": _verdict(queue).lead if label != "No tasks" else "",
    }


def overview(
    worker: ComponentStatus, held: dict[str, int] | None = None
) -> dict[str, Any]:
    """Every queue, with its share of the backlog and of the finished work,
    and the worker's totals. ``held``: reported capacity per queue."""
    group = worker.sub_components.get("queues")
    queues = [
        queue_view(q, (held or {}).get(name))
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


def sparkline(values: list[int], width: float = 100, height: float = 24) -> str:
    """SVG polyline points for ``values`` across a ``width`` by ``height``
    box, highest at the top; a flat line sits on the floor."""
    if not values:
        return ""
    if len(set(values)) == 1:
        # Steady: one line, on the floor when empty, midway otherwise, so a
        # quiet queue draws the same however many samples it has.
        y = height if values[0] == 0 else height / 2
        return f"0.0,{y:.1f} {width:.1f},{y:.1f}"
    top = max(values)
    step = width / (len(values) - 1)
    return " ".join(
        f"{i * step:.1f},{height - v / top * height:.1f}" for i, v in enumerate(values)
    )


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
        return ComponentStatus(name="worker", message="No worker installed")
    return await check_worker_health()


async def load_runtime() -> list[dict[str, str]]:
    """What each live worker process reports it is running with."""
    try:
        from app.components.worker.runtime import read_runtime
    except ImportError:
        return []
    from app.services.system.redis_keys import redis_client

    client = redis_client()
    try:
        return await read_runtime(client)
    finally:
        await client.aclose()


def held(reports: list[dict[str, str]]) -> dict[str, int]:
    """Jobs each queue's reporting processes may hold, summed."""
    found: dict[str, int] = {}
    for r in reports:
        if r.get("concurrency", "").isdigit():
            found[r["queue"]] = found.get(r["queue"], 0) + int(r["concurrency"])
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
