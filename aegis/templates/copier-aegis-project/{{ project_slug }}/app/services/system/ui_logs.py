"""Container logs, as Overseer shows them in htmx and Flet alike: one
page's (its Logs section) or several pages' (Overseer > Logs).

``containers(pages)`` looks up the containers behind ``pages`` (the
containers sampler's reading, ``ui_runtime``), once for a view's pickers
(``sources``) and its lines. ``recent(pages, query)`` reads the last lines
of every container behind ``pages``,
merged by time, newest first. ``follow(pages, query)`` yields new lines in
batches as the containers write them; Docker pushes them, so following
polls nothing. Both fold a traceback into the line it belongs to and
apply the filters a query carries: ``window`` (one of ``WINDOWS``),
``level`` (the levels picked), ``q`` (text), ``from`` and ``to`` (a
time range in ms, a volume bar's) and ``order`` (one of ``ORDERS``).
``recent`` also counts the window's lines by tone (``volume``). No UI
framework imports.
"""

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import os
import time
from typing import Any, Self

from app.core import runtime, series
from app.core.formatting import format_relative_time, format_timestamp
from app.core.log import logger
from app.core.log_records import LogAssembler, LogRecord
from app.core.log_records import split_lead as _split_lead
from app.core.runtime import (
    METADATA_KEYS,
    LogLine,
    RuntimeUnavailableError,
    without_metadata,
)
from app.core.time import utcnow
from app.services.system import ui_runtime
from app.services.system.ui import get_component_title

# The windows the logs offer, in seconds, labelled as every range chip row
# labels them; "All" reads each container from its start.
ALL = 0
WINDOWS: tuple[tuple[int, str], ...] = (
    (900, "15m"),
    (3600, "1h"),
    (21600, "6h"),
    (86400, "1d"),
    (ALL, "All"),
)
DEFAULT_WINDOW = 900
ORDERS = (("desc", "Newest first"), ("asc", "Oldest first"))
DEFAULT_ORDER = "desc"
LEVELS = ("debug", "info", "warning", "error", "critical")
# The level filter's pick for a line with no level (Redis's, a plain print).
NO_LEVEL = "none"
# What the level filter offers, in both UIs.
LEVEL_CHOICES = (
    *((level, level.capitalize()) for level in LEVELS),
    (NO_LEVEL, "No level"),
)
# A level's tone (badge, edge, volume stack); info and none stay plain.
TONES = {"debug": "muted", "warning": "warn", "error": "error", "critical": "error"}
TAIL = 500  # the most lines read from each container
# How long a followed line waits for the traceback that may follow it.
FLUSH_SECONDS = 0.5
# The volume above the lines: the window in this many bars, each line
# counted in its tone's stack.
VOLUME_BARS = 60
VOLUME_TONES = ("error", "warn", "other")
# The chart ramp both UIs draw with (--aegis-chart-1..8, ChartColors.RAMP):
# a service's lines take one of its colors.
RAMP = 8
_PAGES = sorted(runtime.PAGES)


def _presentation(
    line: LogLine, message: str
) -> tuple[str, list[tuple[str, str]], list[tuple[str, str]]]:
    """Keep attribution metadata out of the collapsed message in both renderers."""
    if line.event is None and line.level:
        message = without_metadata(message)
    return (
        message,
        [(key, value) for key, value in line.fields if key not in METADATA_KEYS],
        [(key, value) for key, value in line.fields if key in METADATA_KEYS],
    )


def color_of(page: str) -> int:
    """A page's color, an index into the chart ramp: the same on every page
    and in both UIs, and (with no more pages than colors) no two alike."""
    return _PAGES.index(page) % RAMP if page in _PAGES else 0


def title_of(page: str) -> str:
    """A page's name, as its component's (``redis`` is the Cache)."""
    return get_component_title(ui_runtime.component_of(page))


@dataclass
class _Row:
    """One line as shown, with the traceback lines folded under it."""

    page: str
    instance: str
    line: LogLine
    # Which of its page's containers, when it has several (``_sources``).
    source: str = ""
    trace: str | None = None

    def view(self) -> dict[str, Any]:
        when = self.line.timestamp
        lead, message = (
            ("", self.line.event) if self.line.event else _split_lead(self.line.text)
        )
        copy_text = lead + message
        message, fields, metadata = _presentation(self.line, message)
        return {
            "at": format_timestamp(when.isoformat()) if when else "-",
            "ms": _ms(when) if when else None,
            "page": self.page,
            "app_service": dict(self.line.fields).get("app_service"),
            "color": color_of(self.page),
            "instance": self.instance,
            "source": self.source,
            "level": self.line.level,
            "prefix": lead,
            "message": message,
            "fields": fields,
            "metadata": metadata,
            "copy_text": copy_text,
            "trace": self.trace,
        }


def _rows(
    page: str, instance: str, lines: list[LogLine], source: str = ""
) -> list[_Row]:
    assembler = LogAssembler(max_bytes=None)
    records: list[LogRecord] = []
    for line in lines:
        records.extend(assembler.feed(instance, line, now=0))
    records.extend(assembler.flush())
    return [_Row(page, instance, r.line, source, r.trace) for r in records]


def _sources(names: list[tuple[str, str]]) -> dict[str, str]:
    """Each container by what its name does not share with its page's other
    containers (``system`` of ``app-worker-system-1``), none when alone."""
    by_page: dict[str, list[str]] = defaultdict(list)
    for page, name in names:
        by_page[page].append(name)
    found: dict[str, str] = {}
    for kept in by_page.values():
        if len(kept) == 1:
            found[kept[0]] = ""
            continue
        head = len(os.path.commonprefix(kept))
        tail = len(os.path.commonprefix([name[::-1] for name in kept]))
        for name in kept:
            found[name] = name[head : max(head, len(name) - tail)].strip("-_") or name
    return found


def _ms(at: datetime) -> int:
    """A log time (naive UTC, as ``runtime`` reads it) in epoch ms."""
    return round(at.replace(tzinfo=UTC).timestamp() * 1000)


def number_of(query: Mapping[str, str], key: str) -> int | None:
    """A whole number a query gives ``key``, None when it gives none."""
    value = query.get(key, "")
    return int(value) if value.isdigit() else None


@dataclass(frozen=True)
class Picked:
    """The services (pages), containers and application services a query
    ticks: a line or error from any of them is kept, every one when none is."""

    services: frozenset[str]
    containers: frozenset[str]
    app_services: frozenset[str]

    @classmethod
    def of(cls, query: Mapping[str, str]) -> Self:
        return cls(
            frozenset(listed(query, "service")),
            frozenset(listed(query, "container")),
            frozenset(listed(query, "app_service")),
        )

    def __bool__(self) -> bool:
        return bool(self.services or self.containers or self.app_services)

    def keeps(self, page: str, container: str | None, app_service: str | None) -> bool:
        return (
            not self
            or page in self.services
            or container in self.containers
            or app_service in self.app_services
        )


def levels_of(query: Mapping[str, str]) -> list[str]:
    """The levels a query picks that the filter knows (``LEVEL_CHOICES``)."""
    known = dict(LEVEL_CHOICES)
    return [level for level in listed(query, "level") if level in known]


@dataclass(frozen=True)
class _Filter:
    """A query's filters, read once: exactly the levels picked (``NO_LEVEL``
    for a line with none), the text (any of what the row shows), and the
    ``from``/``to`` range (ms, ``to`` excluded) a volume bar picks."""

    levels: frozenset[str]
    text: str
    start: int | None
    end: int | None
    picked: Picked

    @classmethod
    def of(cls, query: Mapping[str, str]) -> Self:
        return cls(
            frozenset(levels_of(query)),
            query.get("q", "").strip().lower(),
            number_of(query, "from"),
            number_of(query, "to"),
            Picked.of(query),
        )

    def keeps(self, row: _Row) -> bool:
        """The level and text filters, and with application services ticked,
        the sources (the pages read and their containers narrow the rest)."""
        app_service = dict(row.line.fields).get("app_service")
        if self.picked.app_services and not self.picked.keeps(
            row.page, row.instance, app_service
        ):
            return False
        if self.levels and (row.line.level or NO_LEVEL) not in self.levels:
            return False
        if not self.text:
            return True
        return self.text in " ".join([row.line.text, row.trace or ""]).lower()

    def in_range(self, row: _Row) -> bool:
        if self.start is None and self.end is None:
            return True
        if row.line.timestamp is None:
            return False
        at = _ms(row.line.timestamp)
        return (self.start is None or at >= self.start) and (
            self.end is None or at < self.end
        )


def order_of(query: Mapping[str, str]) -> str:
    """The order a query asks for, the newest first unless it names another."""
    order = query.get("order", "")
    return order if order in dict(ORDERS) else DEFAULT_ORDER


def _ordered(rows: list[_Row], order: str) -> list[dict[str, Any]]:
    """``rows`` as shown, in ``order``."""
    rows = sorted(rows, key=lambda row: row.line.timestamp or datetime.min)
    if order == "desc":
        rows.reverse()
    return [row.view() for row in rows]


def _volume(
    kept: list[_Row], since: datetime | None, picked: _Filter
) -> list[dict[str, Any]]:
    """The window in ``VOLUME_BARS`` bars (``from`` and ``to`` in ms), each
    counting the lines the level and text filters keep, by tone, whatever
    range a bar narrowed the lines to; a bar inside that range is
    ``picked``."""
    end = utcnow()
    first = min((r.line.timestamp for r in kept if r.line.timestamp), default=end)
    start = (
        since.replace(tzinfo=None)
        if since
        else min(first, end - timedelta(seconds=DEFAULT_WINDOW))
    )
    step = max((end - start) / VOLUME_BARS, timedelta(milliseconds=1))
    lo, hi = picked.start, picked.end
    bars = []
    for i in range(VOLUME_BARS):
        frm, to = _ms(start + i * step), _ms(start + (i + 1) * step)
        middle = (frm + to) // 2
        bars.append(
            {
                "from": frm,
                "to": to,
                # How long ago it starts (a day or more back, its date).
                "at": format_relative_time(
                    start + i * step, now=end.replace(tzinfo=UTC)
                ),
                "picked": lo is not None and hi is not None and lo <= middle < hi,
                **dict.fromkeys(VOLUME_TONES, 0),
            }
        )
    for row in kept:
        at = row.line.timestamp
        if at is None or at < start:
            continue
        tone = TONES.get(row.line.level or "")
        bar = bars[min(int((at - start) / step), VOLUME_BARS - 1)]
        bar[tone if tone in ("warn", "error") else "other"] += 1
    for bar in bars:
        bar["total"] = sum(bar[tone] for tone in VOLUME_TONES)
    return bars


def listed(query: Mapping[str, str], key: str) -> list[str]:
    """Every value ``query`` gives ``key`` (a multi-select's picks)."""
    getlist = getattr(query, "getlist", None)
    if getlist is not None:
        return list(getlist(key))
    return [query[key]] if query.get(key) else []


@dataclass(frozen=True)
class Containers:
    """The containers behind some pages, each as ``(page, container)``, and
    each page's reason when it has none: one lookup a view's pickers and
    lines share."""

    names: list[tuple[str, str]]
    notes: dict[str, str | None]

    @property
    def note(self) -> str | None:
        """Why there are none (the first page's reason); None when there are."""
        return None if self.names else next(iter(self.notes.values()), None)

    def of(self, pages: Sequence[str]) -> Self:
        """Only those behind ``pages``, with their own reasons."""
        return replace(
            self,
            names=[(page, name) for page, name in self.names if page in pages],
            notes={page: note for page, note in self.notes.items() if page in pages},
        )


async def containers(pages: Sequence[str] | None = None) -> Containers:
    """Each page's containers, every page's when ``pages`` is None."""
    pages = _PAGES if pages is None else list(pages)
    views = await ui_runtime.containers_of(pages)
    return Containers(
        [(page, row["name"]) for page in pages for row in views[page]["rows"]],
        {page: views[page]["note"] for page in pages},
    )


def _narrowed(
    names: list[tuple[str, str]], query: Mapping[str, str]
) -> list[tuple[str, str]]:
    """``names`` with a page that has a ``container`` picked keeping only the
    picked ones."""
    if listed(query, "app_service"):
        return names  # Service origins can occur in any container; filter rows below.
    picked = set(listed(query, "container"))
    narrowed = {page for page, name in names if name in picked}
    return [(p, n) for p, n in names if p not in narrowed or n in picked]


def sources(found: Containers) -> list[dict[str, Any]]:
    """The pages with a container behind them, each with its title and, for
    a page with several, each container and what tells it apart: what a
    Logs view can pick from."""
    short = _sources(found.names)
    pages = dict.fromkeys(page for page, _ in found.names)
    picks = [
        {
            "page": page,
            "title": title_of(page),
            "containers": [
                {"name": name, "label": short[name]}
                for p, name in found.names
                if p == page and short[name]
            ],
        }
        for page in pages
    ]
    return sorted(picks, key=lambda source: source["title"])


async def recent(
    pages: Sequence[str],
    query: Mapping[str, str],
    *,
    volume: bool = False,
    found: Containers | None = None,
) -> dict[str, Any]:
    """``{"lines": [...], "volume": [...], "note": str | None}``: the
    window's lines from every container behind ``pages`` (of those already
    ``found``, else looked up) that pass the filters, in the query's order,
    and, asked for, their ``volume``."""
    behind = found.of(pages) if found else await containers(pages)
    every, note = behind.names, behind.note
    source = _sources(every)  # what tells a container apart, picked or not
    names = _narrowed(every, query)
    if not names:
        return {"lines": [], "volume": [], "note": note}
    window = series.window_of(query.get("window"), WINDOWS, DEFAULT_WINDOW)
    since = None if window == ALL else datetime.now(UTC) - timedelta(seconds=window)
    try:
        read = await asyncio.gather(
            *(runtime.logs(name, tail=TAIL, since=since) for _, name in names)
        )
    except RuntimeUnavailableError as exc:
        return {"lines": [], "volume": [], "note": f"The runtime did not answer: {exc}"}
    rows = [
        row
        for (page, name), lines in zip(names, read, strict=True)
        for row in _rows(page, name, lines, source[name])
    ]
    picked = _Filter.of(query)
    kept = [row for row in rows if picked.keeps(row)]
    return {
        "lines": _ordered([r for r in kept if picked.in_range(r)], order_of(query)),
        "volume": _volume(kept, since, picked) if volume else [],
        "note": None,
    }


async def follow(
    pages: Sequence[str],
    query: Mapping[str, str],
    *,
    found: Containers | None = None,
) -> AsyncIterator[list[dict[str, Any]]]:
    """New lines from every container behind ``pages`` (of those already
    ``found``, else looked up) as they are written, in batches in the
    query's order, each line once its traceback (if any) has arrived."""
    every = (found.of(pages) if found else await containers(pages)).names
    source = _sources(every)
    names = _narrowed(every, query)
    if not names:
        return
    page_by_name = {name: page for page, name in names}
    picked, order = _Filter.of(query), order_of(query)

    def shown(records: list[LogRecord]) -> list[dict[str, Any]]:
        rows = [
            _Row(page_by_name[r.source], r.source, r.line, source[r.source], r.trace)
            for r in records
        ]
        return _ordered(
            [r for r in rows if picked.keeps(r) and picked.in_range(r)], order
        )

    arrived: asyncio.Queue[tuple[str, LogLine | None]] = asyncio.Queue()
    pumps = [asyncio.create_task(_pump(name, arrived)) for _, name in names]
    assembler = LogAssembler(max_bytes=None, idle_seconds=FLUSH_SECONDS)
    open_streams = len(names)
    try:
        while open_streams:
            try:
                name, line = await asyncio.wait_for(arrived.get(), FLUSH_SECONDS)
            except TimeoutError:
                ready = assembler.flush(now=time.monotonic())
            else:
                if line is None:
                    open_streams -= 1
                    ready = assembler.flush(name)
                else:
                    ready = assembler.feed(name, line, now=time.monotonic())
                    ready.extend(assembler.flush(now=time.monotonic()))
            if batch := shown(ready):
                yield batch
        if batch := shown(assembler.flush()):
            yield batch
    finally:
        for pump in pumps:
            pump.cancel()
        await asyncio.gather(*pumps, return_exceptions=True)


async def _pump(name: str, arrived: asyncio.Queue[tuple[str, LogLine | None]]) -> None:
    """One container's followed lines onto the shared queue, then its end."""
    try:
        async for line in runtime.follow(name):
            await arrived.put((name, line))
    except RuntimeUnavailableError as exc:
        logger.warning("ui_logs.follow_failed", container=name, error=str(exc))
    finally:
        await arrived.put((name, None))
