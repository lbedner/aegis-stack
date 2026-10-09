"""The containers behind an Overseer page, as Overseer shows them in htmx
and Flet alike.

``sample()`` is the containers sampler (``app.core.series``): one read of
every container a tick, kept as each page's table and each container's CPU
and memory. ``containers(page)`` serves a page from that reading (and keeps
the sampler at full pace while someone looks), reading ``app.core.runtime``
itself only before the first sample: a row per instance, or, when there is
nothing to read, why: no deploy target, no container behind the page, or a
runtime that did not answer. No UI framework imports.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.core import runtime, series, thresholds
from app.core.config import settings
from app.core.formatting import format_bytes, format_percentage, format_span
from app.core.runtime import Instance, RuntimeUnavailableError, Stats
from app.core.series import Sample, Sampler

NO_DEPLOY = (
    "No deploy target: this process is all the app can see. Add the deploy "
    "component (aegis add deploy) to see each container."
)
NO_CONTAINER = "No container runs this part of the app."
SAMPLER = "containers"
# The restart API (behind ``get_admin_actor``), which both UIs'
# Restart calls.
RESTART_API = "/api/v1/runtime/containers/{name}/restart"
RESTART_TITLE = "Restart container"
CPU, MEMORY = "cpu", series.MEMORY  # each container's gauges, and charts
# Running totals since the container started; their charts read the rate.
NET_IN, NET_OUT, DISK_READ, DISK_WRITE = "net_in", "net_out", "disk_read", "disk_write"
# Each live figure's name, in both UIs and on its chart.
FIGURES = {CPU: "CPU", MEMORY: "Memory", "network": "Network", "disk": "Disk I/O"}
# Shown only before the containers sampler's first reading.
PENDING = {"rows": [], "note": "Reading the containers.", "pending": True}
# Health component -> its Overseer page, where the two names differ.
_COMPONENT_PAGES = {"backend": "server", "cache": "redis", "ollama": "inference"}


@dataclass(frozen=True)
class Chart:
    """One chart: the series under ``prefix`` (``{page}`` filled in) whose
    name ends ``:<metric>``, a line each, read in ``fmt``; ``lines`` instead
    charts several metrics, each line named for its own (``in``, ``out``);
    ``rate`` reads running totals as per second. With ``within``, only the
    lines that chart on the same page has. ``empty`` is what it says with
    nothing in its window (``{window}``: "the last hour")."""

    key: str
    title: str
    prefix: str
    metric: str
    fmt: str | None = None
    within: str | None = None
    empty: str = "Nothing in {window}."
    style: str | None = None  # see ``series.chart``
    lines: tuple[tuple[str, str], ...] = ()
    rate: bool = False
    # Where warning and alert begin, as lines across the chart: the row key
    # of what a container has of it, and the setting naming the alert share.
    limit: tuple[str, str] | None = None


CONTAINER_CHARTS = (
    Chart(
        CPU,
        FIGURES[CPU],
        SAMPLER + ":{page}:",
        CPU,
        "percent",
        limit=("cpu_capacity", "CPU_THRESHOLD_PERCENT"),
    ),
    Chart(
        MEMORY,
        FIGURES[MEMORY],
        SAMPLER + ":{page}:",
        MEMORY,
        "bytes",
        limit=("memory_capacity", "MEMORY_THRESHOLD_PERCENT"),
    ),
    Chart(
        "network",
        FIGURES["network"],
        SAMPLER + ":{page}:",
        NET_IN,
        "bytes_per_second",
        lines=((NET_IN, "in"), (NET_OUT, "out")),
        rate=True,
    ),
    Chart(
        "disk",
        FIGURES["disk"],
        SAMPLER + ":{page}:",
        DISK_READ,
        "bytes_per_second",
        lines=((DISK_READ, "read"), (DISK_WRITE, "write")),
        rate=True,
    ),
)


@dataclass(frozen=True)
class Host:
    """A page whose server can run outside Docker: what to say, and what it
    reports of itself to chart instead of a container."""

    note: str
    charts: tuple[Chart, ...]


def restart_confirm(name: str, own: bool = False) -> str:
    """What both UIs' Restart confirm says before it restarts ``name``;
    ``own``: the server Overseer itself runs on."""
    said = (
        f"Restart {name}? It stops and starts again; whatever it is doing "
        "is interrupted, and requests to it fail for a few seconds."
    )
    if own:
        said += " Overseer runs on it: this page drops, and reconnects when it is back."
    return said


def restart_done(name: str, own: bool) -> str:
    """What both UIs say once the restart API answered: the server Overseer
    runs on is still restarting when it answers."""
    return f"{name} is restarting" if own else f"{name} restarted"


def host_of(page: str) -> Host | None:
    """A page whose server can run outside Docker (Ollama on the host), as
    the component that owns it registers it (``samplers.HOSTS``): looked up
    at call time, since the registry imports this module."""
    from app.services.system.samplers import HOSTS

    return HOSTS.get(page)


def page_of(component: str) -> str | None:
    """The page a health component's containers show on, if any has one."""
    page = _COMPONENT_PAGES.get(component, component)
    return page if page in runtime.PAGES else None


def component_of(page: str) -> str:
    """The health component a page shows (``page_of`` the other way)."""
    return next((c for c, p in _COMPONENT_PAGES.items() if p == page), page)


async def sample() -> Sample:
    """Every container that belongs on a page, read once: CPU (once there is
    a reading to compare with) and memory by ``page:name``, and each page's
    table as ``latest``. Nothing without a deploy target."""
    if not runtime.deployed():
        return Sample()
    pages: dict[str, list[Instance]] = {}
    for service in await runtime.services():
        if service.page:
            pages.setdefault(service.page, []).extend(service.instances)
    everyone = [i for group in pages.values() for i in group]
    read = dict(
        zip(
            (i.id for i in everyone),
            await asyncio.gather(*(_stats(i) for i in everyone)),
            strict=True,
        )
    )
    values: dict[str, float] = {}
    for page, group in pages.items():
        for instance in group:
            if (stats := read[instance.id]) is None:
                continue
            if stats.cpu_percent is not None:
                values[f"{page}:{instance.name}:{CPU}"] = stats.cpu_percent
            values[f"{page}:{instance.name}:{MEMORY}"] = stats.memory_used
            values[f"{page}:{instance.name}:{NET_IN}"] = stats.network_rx
            values[f"{page}:{instance.name}:{NET_OUT}"] = stats.network_tx
            values[f"{page}:{instance.name}:{DISK_READ}"] = stats.disk_read
            values[f"{page}:{instance.name}:{DISK_WRITE}"] = stats.disk_write
    tables = {
        page: {"rows": [_row(i, read[i.id]) for i in group], "note": None}
        for page, group in pages.items()
    }
    return Sample(values, tables)


CONTAINERS = Sampler(SAMPLER, sample)


async def containers(page: str, *, wait: bool = True) -> dict[str, Any]:
    """``{"rows": [...], "note": str | None}`` for one page; a page whose
    server runs outside Docker says so (``host_of``). Before the first
    sample, ``wait=False`` gives ``PENDING`` rather than read the runtime."""
    return (await containers_of([page], wait=wait))[page]


async def containers_of(
    pages: list[str], *, wait: bool = True
) -> dict[str, dict[str, Any]]:
    """``containers`` for each of ``pages``, from one reading of the sampler
    (``_reading``)."""
    tables, note = await _reading(pages, wait)
    return {page: _view(page, tables, note) for page in pages}


async def section(
    page: str, window: int = series.DEFAULT_WINDOW, *, wait: bool = True
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A page's Container section, its ``containers`` and its ``charts``,
    from one reading of the sampler."""
    tables, note = await _reading([page], wait)
    return _view(page, tables, note), await charts(page, window, tables)


async def _reading(
    pages: list[str], wait: bool
) -> tuple[dict[str, Any] | None, str | None]:
    """The sampler's reading for ``pages`` (``series.current``), or why
    there is none. Pages whose servers can all run outside Docker read its
    last reading without keeping Docker at full pace for them."""
    if not runtime.deployed():
        return None, NO_DEPLOY
    try:
        return await (
            series.latest(SAMPLER)
            if all(host_of(page) for page in pages)
            else series.current(CONTAINERS, fill=wait)
        ), None
    except RuntimeUnavailableError as exc:
        return None, f"The runtime did not answer: {exc}"


def _view(page: str, tables: dict[str, Any] | None, note: str | None) -> dict[str, Any]:
    """One page's table from a reading, or why it has none."""
    host = host_of(page)
    if note:
        view = _note(note)
    elif tables is None:
        view = PENDING if host is None else _note(NO_CONTAINER)
    else:
        view = tables.get(page) or _note(NO_CONTAINER)
    return _note(host.note) if host and not view["rows"] else view


def _note(text: str) -> dict[str, Any]:
    """A page with no rows, and why."""
    return {"rows": [], "note": text}


async def charts(
    page: str,
    window: int = series.DEFAULT_WINDOW,
    tables: dict[str, Any] | None | Literal["latest"] = "latest",
) -> list[dict[str, Any]]:
    """The page's charts from what was sampled (no runtime call): its
    containers', or, for a server outside Docker, what it reports of itself
    (``host_of``), over the last ``window`` seconds.
    ``[{"key", "title", "subtitle", "data", "empty"}]``; empty with nothing
    to chart. ``tables``: a reading already in hand (``section``)."""
    if tables == "latest":
        tables = await series.latest(SAMPLER) if runtime.deployed() else None
    rows = ((tables or {}).get(page) or {}).get("rows", [])
    specs = _charts_for(page, tables)
    words = series.phrase(window)
    read: dict[str, dict[str, list[tuple[float, float]]]] = {}
    lines: dict[str, set[str]] = {}
    drawn = []
    for spec in specs:
        prefix = spec.prefix.format(page=page)
        if prefix not in read:
            read[prefix] = await series.read(prefix, window, viewed=True)
        found = lines_of(spec, read[prefix], lines.get(spec.within or ""))
        lines[spec.key] = {_label(name) for name in found}
        data = series.chart(
            found,
            label=_line_label(spec),
            fmt=spec.fmt,
            window=window,
            style=spec.style,
            thresholds=_thresholds(spec, rows),
        )
        drawn.append(entry(spec, data, words))
    return drawn


def entry(spec: Chart, data: dict[str, Any], words: str) -> dict[str, Any]:
    """One drawn chart as views take it; ``words``: its window phrased."""
    return {
        "key": spec.key,
        "title": spec.title,
        "subtitle": words.removeprefix("the ").capitalize(),
        "data": data,
        "empty": spec.empty.format(window=words),
    }


def _charts_for(page: str, tables: dict[str, Any] | None) -> tuple[Chart, ...]:
    """A page's container charts; for one whose server can run outside
    Docker, its own when no container runs it (the last reading says)."""
    host = host_of(page)
    if host is None:
        return CONTAINER_CHARTS if runtime.deployed() else ()
    return CONTAINER_CHARTS if tables and tables.get(page) else host.charts


def _thresholds(spec: Chart, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Where warning and alert begin on ``spec``'s chart (``thresholds``);
    none when its containers differ in what they
    have (one line cannot mark two limits) or it has no limit."""
    if spec.limit is None:
        return []
    key, setting = spec.limit
    capacities = {row[key] for row in rows if row.get(key)}
    if len(capacities) != 1:
        return []
    return thresholds.levels(capacities.pop() * getattr(settings, setting) / 100)


async def trends(
    pages: list[str], window: int = series.DEFAULT_WINDOW
) -> dict[str, dict[str, list[float]]]:
    """``{page: {"cpu": [...], "memory": [...]}}``: each page's CPU and
    memory over the window, each tick's containers added together (a card's
    lines), from one read."""
    found = await series.read(
        f"{SAMPLER}:", window, viewed=True, ending=(f":{CPU}", f":{MEMORY}")
    )
    return {page: _trend(page, found) for page in pages}


def _trend(
    page: str, found: dict[str, list[tuple[float, float]]]
) -> dict[str, list[float]]:
    def metric(name: str) -> str | None:
        owner, *_, measured = name.split(":")
        return measured if owner == page and measured in (CPU, MEMORY) else None

    totals = added(found, metric)
    return {m: [v for _, v in totals.get(m, [])] for m in (CPU, MEMORY)}


def added(
    found: dict[str, list[tuple[float, float]]], group: Callable[[str], str | None]
) -> dict[str, list[tuple[float, float]]]:
    """The series added together, tick by tick, within each ``group`` a
    series' name gives (None leaves it out)."""
    totals: dict[str, dict[float, float]] = {}
    for name, points in found.items():
        if (key := group(name)) is None:
            continue
        total = totals.setdefault(key, {})
        for at, value in points:
            total[at] = total.get(at, 0.0) + value
    return {key: sorted(total.items()) for key, total in totals.items()}


def lines_of(
    spec: Chart,
    read: dict[str, list[tuple[float, float]]],
    within: set[str] | None,
) -> dict[str, list[tuple[float, float]]]:
    """The series ``spec`` charts (its metric, or each of its ``lines``),
    as rates when it reads running totals."""
    metrics = {metric for metric, _ in spec.lines} or {spec.metric}
    return {
        name: _per_second(points) if spec.rate else points
        for name, points in read.items()
        if name.rsplit(":", 1)[-1] in metrics
        and (within is None or _label(name) in within)
    }


def _line_label(spec: Chart) -> Callable[[str], str]:
    """A line's name: the series' (``qwen2.5:7b``), and, with ``lines``,
    which of them (``app-redis-1 in``)."""
    words = dict(spec.lines)
    return lambda name: (
        f"{_label(name)} {words[name.rsplit(':', 1)[-1]]}" if words else _label(name)
    )


def _per_second(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """A running total's rate between each two readings; a total that went
    down (the container restarted, its counters reset) is no rate."""
    return [
        (t2, (v2 - v1) / (t2 - t1))
        for (t1, v1), (t2, v2) in zip(points, points[1:], strict=False)
        if t2 > t1 and v2 >= v1
    ]


def _label(name: str) -> str:
    """A series' line: its name without the metric (``qwen2.5:7b``)."""
    return name.rsplit(":", 1)[0]


async def _stats(instance: Instance) -> Stats | None:
    """A stopped container has nothing to read."""
    return await runtime.stats(instance.id) if instance.state == "running" else None


def _row(instance: Instance, stats: Stats | None) -> dict[str, Any]:
    """One instance's row; a stopped one (no stats) has the same keys."""
    return {
        "name": instance.name,
        "id": instance.id,
        **_state(instance),
        # Its parts too, for a view that shows them apart (htmx's cards).
        "phase": instance.state,
        "health": instance.health or "",
        "restarts": "-" if instance.restarts is None else str(instance.restarts),
        "uptime": format_span(instance.uptime_seconds) or "-",
        "image": " ".join(p for p in (instance.image, instance.build) if p) or "-",
    } | _figures(stats)


def _state(instance: Instance) -> dict[str, str]:
    """Its word and status (read like ``cpu_status``): stopped is down; a
    failing healthcheck while it serves, or starting, is a warning."""
    if instance.state in ("exited", "dead"):
        return {"state": instance.state, "state_status": "unhealthy"}
    sick = instance.health == "unhealthy"
    fine = instance.state == "running" and not sick
    word = "unhealthy" if sick else instance.state
    return {"state": word, "state_status": "healthy" if fine else "warning"}


# A stopped container's live figures: none.
_LIVE = (
    "cpu_value",
    "memory_value",
    "memory_percent",
    "cpu_status",
    "memory_status",
    "cpu_capacity",
    "memory_capacity",
)
_FIGURES = (
    "cpu",
    "memory",
    "network",
    "disk",
    "memory_used",
    "network_in",
    "network_out",
    "disk_read",
    "disk_write",
)


def _figures(stats: Stats | None) -> dict[str, Any]:
    """A row's live figures, whole (``memory``) and in parts (``memory_used``)."""
    if stats is None:
        return (
            dict.fromkeys(_FIGURES, "-") | dict.fromkeys(_LIVE) | {"memory_limit": ""}
        )
    used, limit = format_bytes(stats.memory_used), stats.memory_limit
    rx, tx = format_bytes(stats.network_rx), format_bytes(stats.network_tx)
    read, write = format_bytes(stats.disk_read), format_bytes(stats.disk_write)
    return {
        "cpu": "-"
        if stats.cpu_percent is None
        else format_percentage(stats.cpu_percent),
        "memory": f"{used} / {format_bytes(limit)}" if limit else used,
        "network": f"in {rx}, out {tx}",
        "disk": f"read {read}, write {write}",
        "memory_used": used,
        # The raw figures, for what sums them (``ui_resources``).
        "cpu_value": stats.cpu_percent,
        "memory_value": stats.memory_used,
        # Creeping toward the limit is what kills a container.
        "memory_percent": round(stats.memory_used / limit * 100, 1) if limit else None,
        "memory_limit": format_bytes(limit) if limit else "",
        "network_in": rx,
        "network_out": tx,
        "disk_read": read,
        "disk_write": write,
        # Each figure against what the container has of it, by the host
        # checks' rule, and that capacity (for the charts' threshold lines).
        "cpu_status": _status(
            stats.cpu_percent, stats.cpus * 100, "CPU_THRESHOLD_PERCENT"
        ),
        "memory_status": _status(stats.memory_used, limit, "MEMORY_THRESHOLD_PERCENT"),
        "cpu_capacity": stats.cpus * 100,
        "memory_capacity": limit,
    }


def _status(value: float | None, capacity: float | None, setting: str) -> str | None:
    """``value``'s share of ``capacity`` against the ``setting`` alert share."""
    if value is None or not capacity:
        return None
    return thresholds.status(value / capacity * 100, getattr(settings, setting)).value
