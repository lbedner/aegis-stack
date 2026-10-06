"""Everything the stack uses at once, for Overseer > Resources. CPU and
memory each split three ways: this stack (its containers, summed), the rest
of the host (what the host checks see in use beyond this stack) and what is
free. Then every container across every page, heaviest first, and a server
that runs on the host rather than in Docker, named (it has no container to
read).

It reads what is already read: the containers sampler's last reading
(``ui_runtime``), the host checks (``health_probes.host_metrics``, cached)
and the host's size (``runtime.host``, once per runtime). On Docker Desktop
the host Docker reports is its VM, so "the host" is the VM's CPU and memory.

``charts`` draws the same over time: each figure a line per part (its
containers added together), stacked so the top edge is this stack, with
the host's in use (``HOST``, a sampler of its own) dashed across CPU and
memory. ``load_costs`` looks inside the webserver, which Docker sees whole:
what each service costs it to load (``load_cost``).
"""

import asyncio
from bisect import bisect_right
from collections.abc import Callable
from typing import Any
import weakref

from app.core import runtime, series
from app.core.formatting import format_bytes
from app.core.log import logger
from app.core.runtime import Host, Runtime, RuntimeUnavailableError
from app.core.series import Sample, Sampler
from app.services.system import health_probes, load_cost, ui_runtime
from app.services.system.ui import get_component_title
from app.services.system.ui_logs import color_of, title_of

HOST_SAMPLER = "host"
HOST_LINE = "Host in use"
# Points across a chart: seven filled bands at a point a second redraw
# slowly on every hover.
MAX_POINTS = 300
CPU, MEMORY = ui_runtime.CPU, series.MEMORY
# The host's size, read once per runtime: it does not change while it runs.
_SIZES: weakref.WeakKeyDictionary[Runtime, Host] = weakref.WeakKeyDictionary()


async def overview(*, wait: bool = True) -> dict[str, Any]:
    """``{"split", "rows", "outside", "note"}``: the CPU and memory split,
    every container, the servers outside Docker, or why there is nothing.
    ``wait=False`` reads only what was sampled (``ui_runtime.containers``)."""
    pages = sorted(runtime.PAGES)
    found = await ui_runtime.containers_of(pages, wait=wait)
    rows = _rows(found)
    view: dict[str, Any] = {
        "split": [],
        "rows": rows,
        "outside": [
            {"page": page, "title": title_of(page), "note": shown.note}
            for page in pages
            if (shown := ui_runtime.host_of(page)) and not found[page]["rows"]
        ],
        "note": None,
    }
    if not rows:  # nothing read of this stack, so nothing to split
        return view | {"note": _note(found)}
    try:
        size = await _size()
    except RuntimeUnavailableError as exc:
        return view | {"note": str(exc)}
    used = _in_use(await health_probes.host_metrics(), size)
    return view | {
        "split": [
            _split(CPU, "CPU", size.cpus * 100, used, rows, _cores),
            _split(MEMORY, "Memory", size.memory, used, rows, format_bytes),
        ]
    }


async def _size() -> Host:
    found = runtime.get_runtime()
    if found not in _SIZES:
        _SIZES[found] = await found.host()
    return _SIZES[found]


def _in_use(checks: dict[str, Any], size: Host) -> dict[str, float]:
    """What the host checks see in use, the one rule the split and the
    host's line both read: memory in bytes, CPU in percent of one core (as
    a container's), each as its share of the host's size."""
    totals = {CPU: size.cpus * 100, MEMORY: size.memory}
    used = {}
    for key, total in totals.items():
        check = checks.get(key)
        percent = (check.metadata or {}).get("percent_used") if check else None
        if isinstance(percent, int | float):
            used[key] = percent / 100 * total
    return used


def _rows(found: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Every container, running ones by memory, the heaviest first, each
    with its share of this stack's memory; stopped ones last."""
    rows = [
        row | {"page": page, "title": title_of(page)}
        for page, view in found.items()
        for row in view["rows"]
    ]
    stack = sum(r["memory_value"] or 0 for r in rows)
    for row in rows:
        used = row["memory_value"]
        row["share"] = round(used / stack * 100, 1) if used and stack else None
    return sorted(rows, key=lambda r: -(r["memory_value"] or -1))


def _note(found: dict[str, dict[str, Any]]) -> str | None:
    """Why no page has a container: the reading's own reason (no deploy
    target, the runtime not answering, not read yet)."""
    notes = (v["note"] for v in found.values() if v["note"])
    return next((n for n in notes if n != ui_runtime.NO_CONTAINER), None)


def _split(
    key: str,
    label: str,
    total: float,
    used: dict[str, float],
    rows: list[dict[str, Any]],
    fmt: Callable[[float], str],
) -> dict[str, Any]:
    """One resource three ways, each part in ``fmt`` too; the host's in use
    and the containers are read moments apart, so neither the rest nor the
    free goes below none."""
    stack = sum(r[f"{key}_value"] or 0 for r in rows)
    host = used.get(key)
    parts = {
        "total": total,
        "stack": stack,
        "rest": None if host is None else max(host - stack, 0),
        "free": None if host is None else max(total - max(host, stack), 0),
    }
    text = {part: "-" if v is None else fmt(v) for part, v in parts.items()}
    return {"key": key, "label": label, **parts, "text": text}


async def load_costs() -> dict[str, Any] | None:
    """``{"core", "rows"}``: what the app's core and each part cost to load,
    the largest first, each ``{"key", "label", "value", "bytes"}`` (its
    name registry key, title, size and bytes); None while it is measured."""
    found = await load_cost.costs()
    if found is None:
        return None
    return {
        "core": format_bytes(found.core),
        "rows": [
            {
                "key": key,
                "label": get_component_title(key),
                "value": format_bytes(cost),
                "bytes": cost,
            }
            for key, cost in sorted(found.parts.items(), key=lambda part: -part[1])
        ],
    }


def _cores(value: float) -> str:
    return f"{value / 100:.1f} cores"


async def charts(window: int = series.DEFAULT_WINDOW) -> list[dict[str, Any]]:
    """``ui_runtime.charts``' four, for the whole stack over ``window``
    seconds: a line a part, stacked; the host's in use dashed on CPU and
    memory. The containers' read leaves watching to ``overview`` (which
    keeps their sampler at full pace)."""
    found, host = await asyncio.gather(
        series.read(f"{ui_runtime.SAMPLER}:", window),
        series.read(f"{HOST_SAMPLER}:", window, viewed=True),
    )
    words = series.phrase(window)
    return [
        ui_runtime.entry(
            spec, _chart(spec, found, host.get(spec.metric), window), words
        )
        for spec in ui_runtime.CONTAINER_CHARTS
    ]


def _chart(
    spec: ui_runtime.Chart,
    found: dict[str, list[tuple[float, float]]],
    host: list[tuple[float, float]] | None,
    window: int,
) -> dict[str, Any]:
    """One figure, its series added up by part (the page a series' name
    starts with: ``worker:app-worker-1:memory``), parts by title, all on
    the stack's ticks."""
    parts = ui_runtime.added(
        ui_runtime.lines_of(spec, found, None), lambda name: name.split(":", 1)[0]
    )
    ticks = sorted({at for points in parts.values() for at, _ in points})
    lines = {
        part: _on(ticks, points)
        for part, points in sorted(parts.items(), key=lambda p: title_of(p[0]))
    }
    if host:
        lines[HOST_SAMPLER] = _held(host, ticks) if ticks else host
    data = series.chart(
        lines,
        label=lambda key: HOST_LINE if key == HOST_SAMPLER else title_of(key),
        fmt=spec.fmt,
        window=window,
        max_points=MAX_POINTS,
        style="stacked",
    )
    for line, key in zip(data["series"], lines, strict=True):
        line |= {"dashed": True} if key == HOST_SAMPLER else {"color": color_of(key)}
    return data


def _on(
    ticks: list[float], points: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """A part on every tick: not read at one (not started yet, or a rate
    dropped at a restart) is nothing there, so no band has a hole."""
    read = dict(points)
    return [(at, read.get(at, 0.0)) for at in ticks]


def _held(
    points: list[tuple[float, float]], ticks: list[float]
) -> list[tuple[float, float]]:
    """``points`` (read at their own moments) on ``ticks``: the last reading
    at or before each; the ticks before the first have none."""
    times = [at for at, _ in points]
    return [(at, points[i - 1][1]) for at in ticks if (i := bisect_right(times, at))]


async def _sample_host() -> Sample:
    """The host's in use (``_in_use``); nothing while the runtime cannot
    say how big the host is."""
    try:
        size = await _size()
    except RuntimeUnavailableError as exc:
        logger.debug(f"Host not sampled: {exc}")
        return Sample()
    return Sample(_in_use(await health_probes.host_metrics(), size))


# About as often as the host checks read anew (``host_metrics`` is cached
# ``SYSTEM_METRICS_CACHE_SECONDS``, 5 by default; a setting saved while the
# app runs is never read at import, so this does not follow it).
HOST = Sampler(HOST_SAMPLER, _sample_host, interval=5.0)
