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
from dataclasses import dataclass
from typing import Any

from app.core import runtime, series
from app.core.formatting import format_bytes, format_percentage, format_span
from app.core.runtime import Instance, RuntimeUnavailableError, Stats
from app.core.series import Sample, Sampler

NO_DEPLOY = (
    "No deploy target: this process is all the app can see. Add the deploy "
    "component (aegis add deploy) to see each container."
)
NO_CONTAINER = "No container runs this part of the app."
SAMPLER = "containers"
CPU, MEMORY = "cpu", series.MEMORY  # each container's two series, and charts
# Shown only before the containers sampler's first reading.
PENDING = {"rows": [], "note": "Reading the containers.", "pending": True}
# A page's table, in both UIs: each column's row key and heading.
COLUMNS = (
    ("name", "Container"),
    ("state", "State"),
    ("cpu", "CPU"),
    ("memory", "Memory"),
    ("network", "Network"),
    ("disk", "Disk I/O"),
    ("restarts", "Restarts"),
    ("uptime", "Up"),
    ("image", "Image"),
)
# Health component -> its Overseer page, where the two names differ.
_COMPONENT_PAGES = {"backend": "server", "cache": "redis", "ollama": "inference"}


@dataclass(frozen=True)
class Chart:
    """One chart: the series under ``prefix`` (``{page}`` filled in) whose
    name ends ``:<metric>``, a line each, read in ``fmt``; with ``within``,
    only the lines that chart on the same page has. ``empty`` is what it
    says with nothing in its window (``{window}``: "the last hour")."""

    key: str
    title: str
    prefix: str
    metric: str
    fmt: str | None = None
    within: str | None = None
    empty: str = "Nothing in {window}."
    style: str | None = None  # see ``series.chart``


CONTAINER_CHARTS = (
    Chart(CPU, "CPU", SAMPLER + ":{page}:", CPU, "percent"),
    Chart(MEMORY, "Memory", SAMPLER + ":{page}:", MEMORY, "bytes"),
)


@dataclass(frozen=True)
class Host:
    """A page whose server can run outside Docker: what to say, and what it
    reports of itself to chart instead of a container."""

    note: str
    charts: tuple[Chart, ...]


HOSTS = {
    "inference": Host(
        "Ollama runs on this machine, outside Docker: what it holds in "
        "memory, and how fast it answers this app.",
        (
            Chart(
                "model-memory",
                "Model memory",
                f"{series.INFERENCE}:",
                series.MEMORY,
                "bytes",
                empty="No model loaded in {window}.",
            ),
            Chart(
                "tokens",
                "Tokens per second",
                f"{series.LLM}:",
                series.TOKENS_PER_SECOND,
                within="model-memory",
                empty="No calls to a loaded model in {window}.",
                style="events",
            ),
            Chart(
                "latency",
                "Latency",
                f"{series.LLM}:",
                series.LATENCY,
                "seconds",
                within="model-memory",
                empty="No calls to a loaded model in {window}.",
                style="events",
            ),
        ),
    ),
}


def page_of(component: str) -> str | None:
    """The page a health component's containers show on, if any has one."""
    page = _COMPONENT_PAGES.get(component, component)
    return page if page in runtime.PAGES else None


async def sample() -> Sample:
    """Every container that belongs on a page, read once: CPU (once there is
    a reading to compare with) and memory by ``page:name``, and each page's
    table as ``latest``. Nothing without a deploy target."""
    if not _deployed():
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
    tables = {
        page: {"rows": [_row(i, read[i.id]) for i in group], "note": None}
        for page, group in pages.items()
    }
    return Sample(values, tables)


CONTAINERS = Sampler(SAMPLER, sample)


async def containers(page: str, *, wait: bool = True) -> dict[str, Any]:
    """``{"rows": [...], "note": str | None}`` for one page; a page whose
    server runs outside Docker says so (``HOSTS``). Before the first
    sample, ``wait=False`` gives ``PENDING`` rather than read the runtime."""
    view = await _containers(page, wait)
    if not view["rows"] and page in HOSTS:
        return _note(HOSTS[page].note)
    return view


async def _containers(page: str, wait: bool) -> dict[str, Any]:
    """A page served from the containers sampler (``series.current``); a
    page whose server can run outside Docker reads its last reading without
    keeping Docker at full pace for it (its charts keep their own)."""
    if not _deployed():
        return _note(NO_DEPLOY)
    try:
        tables = await (
            series.latest(SAMPLER)
            if page in HOSTS
            else series.current(CONTAINERS, fill=wait)
        )
    except RuntimeUnavailableError as exc:
        return _note(f"The runtime did not answer: {exc}")
    if tables is not None:
        return _page(tables, page)
    return _note(NO_CONTAINER) if page in HOSTS else PENDING


def _deployed() -> bool:
    return runtime.get_runtime().backend_name != "none"


def _page(tables: dict[str, Any], page: str) -> dict[str, Any]:
    """One page's table from a reading, or why it has none."""
    return tables.get(page) or _note(NO_CONTAINER)


def _note(text: str) -> dict[str, Any]:
    """A page with no rows, and why."""
    return {"rows": [], "note": text}


async def charts(
    page: str, window: int = series.DEFAULT_WINDOW
) -> list[dict[str, Any]]:
    """The page's charts from what was sampled (no runtime call): its
    containers', or, for a server outside Docker, what it reports of itself
    (``HOSTS``), over the last ``window`` seconds.
    ``[{"key", "title", "subtitle", "data", "empty"}]``; empty with nothing
    to chart."""
    specs = await _charts_for(page)
    words = series.phrase(window)
    read: dict[str, dict[str, list[tuple[float, float]]]] = {}
    lines: dict[str, set[str]] = {}
    drawn = []
    for spec in specs:
        prefix = spec.prefix.format(page=page)
        if prefix not in read:
            read[prefix] = await series.read(prefix, window, viewed=True)
        found = {
            name: points
            for name, points in read[prefix].items()
            if name.endswith(f":{spec.metric}")
            and (spec.within is None or _label(name) in lines[spec.within])
        }
        lines[spec.key] = {_label(name) for name in found}
        data = series.chart(
            found, label=_label, fmt=spec.fmt, window=window, style=spec.style
        )
        drawn.append(
            {
                "key": spec.key,
                "title": spec.title,
                "subtitle": words.removeprefix("the ").capitalize(),
                "data": data,
                "empty": spec.empty.format(window=words),
            }
        )
    return drawn


async def _charts_for(page: str) -> tuple[Chart, ...]:
    """A page's container charts; for one whose server can run outside
    Docker, its own when no container runs it (the last reading says)."""
    if page not in HOSTS:
        return CONTAINER_CHARTS if _deployed() else ()
    tables = await series.latest(SAMPLER) if _deployed() else None
    return CONTAINER_CHARTS if tables and tables.get(page) else HOSTS[page].charts


def _label(name: str) -> str:
    """A series' line: its name without the metric (``qwen2.5:7b``)."""
    return name.rsplit(":", 1)[0]


async def _stats(instance: Instance) -> Stats | None:
    """A stopped container has nothing to read."""
    return await runtime.stats(instance.id) if instance.state == "running" else None


def _row(instance: Instance, stats: Stats | None) -> dict[str, str]:
    health = f" ({instance.health})" if instance.health else ""
    row = {
        "name": instance.name,
        "state": f"{instance.state}{health}",
        "restarts": "-" if instance.restarts is None else str(instance.restarts),
        "uptime": format_span(instance.uptime_seconds) or "-",
        "image": " ".join(p for p in (instance.image, instance.build) if p) or "-",
        "cpu": "-",
        "memory": "-",
        "network": "-",
        "disk": "-",
    }
    if stats is not None:
        limit = f" / {format_bytes(stats.memory_limit)}" if stats.memory_limit else ""
        row |= {
            "cpu": "-"
            if stats.cpu_percent is None
            else format_percentage(stats.cpu_percent),
            "memory": f"{format_bytes(stats.memory_used)}{limit}",
            "network": f"in {format_bytes(stats.network_rx)}, out {format_bytes(stats.network_tx)}",
            "disk": f"read {format_bytes(stats.disk_read)}, write {format_bytes(stats.disk_write)}",
        }
    return row
