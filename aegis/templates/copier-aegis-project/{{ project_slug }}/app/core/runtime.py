"""What is running and how it is doing, behind one interface.

Every project has this, the way it has ``app.core.storage`` and
``app.core.secrets``. Without a deploy target the backend is the app's
own process (psutil), so a page that reads it renders anywhere. The
deploy component plugs in the Docker backend (``BACKEND_MODULE``), found
on first use the way the secrets store is, so no process needs a startup
hook: it reads the compose project's containers through the socket proxy.

Calls are async and return plain dataclasses; a backend that cannot be
reached raises ``RuntimeUnavailableError`` rather than inventing numbers.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import import_module
import json
import os
import re
from typing import Protocol

import psutil

from app.core.time import as_stored, utcnow

# Where the deploy component keeps its backend; absent in stacks without it.
BACKEND_MODULE = "app.components.deploy.docker"

# Compose service -> the Overseer page that shows it. Workers are named
# per queue (``worker-system``), so they match on the prefix.
_PAGES = {
    "webserver": "server",
    "scheduler": "scheduler",
    "redis": "redis",
    "postgres": "database",
    "seaweedfs": "storage",
    "traefik": "ingress",
    "ollama": "inference",
}

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_STAMPED = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?Z ?(.*)$", re.S)


class RuntimeUnavailableError(RuntimeError):
    """The backend could not answer (no socket, proxy down, path refused)."""


@dataclass(frozen=True)
class Instance:
    """One running copy of a service: a container, or this process."""

    id: str
    name: str
    service: str
    state: str
    health: str | None = None
    # None where the backend cannot know (Docker's list has no count).
    restarts: int | None = None
    started_at: datetime | None = None
    image: str | None = None
    build: str | None = None

    @property
    def uptime_seconds(self) -> float | None:
        if self.started_at is None or self.state != "running":
            return None
        return max((utcnow() - self.started_at).total_seconds(), 0.0)


@dataclass(frozen=True)
class Service:
    name: str
    instances: list[Instance]

    @property
    def page(self) -> str | None:
        return page_for(self.name)


@dataclass(frozen=True)
class Stats:
    cpu_percent: float
    memory_used: int
    memory_limit: int | None
    network_rx: int = 0
    network_tx: int = 0
    disk_read: int = 0
    disk_write: int = 0


@dataclass(frozen=True)
class LogLine:
    text: str
    stream: str
    timestamp: datetime | None = None
    level: str | None = None
    event: str | None = None


@dataclass(frozen=True)
class DiskUsage:
    """Bytes per container (writable layer) and per named volume."""

    containers: dict[str, int] = field(default_factory=dict)
    volumes: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Host:
    cpus: int
    memory: int
    docker_version: str | None
    disk_total: int
    disk_free: int


class Runtime(Protocol):
    backend_name: str

    async def services(self) -> list[Service]: ...

    async def stats(self, instance: str) -> Stats: ...

    async def logs(
        self, instance: str, tail: int = 200, since: datetime | None = None
    ) -> list[LogLine]: ...

    def follow(self, instance: str) -> AsyncIterator[LogLine]: ...

    async def disk(self) -> DiskUsage: ...

    async def host(self) -> Host: ...


def page_for(service: str) -> str | None:
    """The Overseer page a compose service belongs on, or None."""
    if service.startswith("worker"):
        return "worker"
    return _PAGES.get(service)


def _stamp(value: str, fraction: str | None) -> datetime:
    """Docker's nanosecond RFC 3339 as naive UTC (microseconds kept)."""
    micro = int((fraction or "0")[:6].ljust(6, "0"))
    return datetime.fromisoformat(value).replace(microsecond=micro)


def parse_log_line(raw: str, stream: str) -> LogLine:
    """One log line: timestamp split off, colour codes stripped, and a JSON
    object (the prod renderer) read for its level and event."""
    timestamp = None
    match = _STAMPED.match(raw)
    if match:
        timestamp = _stamp(match.group(1), match.group(2))
        raw = match.group(3)
    text = _ANSI.sub("", raw).rstrip("\r\n")
    level = event = None
    if text.startswith("{"):
        try:
            record = json.loads(text)
        except ValueError:
            record = None
        if isinstance(record, dict):
            level = record.get("level") or record.get("levelname")
            event = record.get("event") or record.get("msg") or record.get("message")
    return LogLine(
        text=text,
        stream=stream,
        timestamp=timestamp,
        level=str(level).lower() if level else None,
        event=str(event) if event is not None else None,
    )


class ProcessRuntime:
    """No deploy target: the app's own process and the machine it is on.
    There are no container logs to read, so ``logs`` is empty."""

    backend_name = "none"

    def __init__(self) -> None:
        self._process = psutil.Process(os.getpid())

    async def services(self) -> list[Service]:
        started = datetime.fromtimestamp(self._process.create_time(), UTC)
        instance = Instance(
            id=str(self._process.pid),
            name=self._process.name(),
            service="webserver",
            state="running",
            started_at=as_stored(started),
        )
        return [Service(name="webserver", instances=[instance])]

    async def stats(self, instance: str) -> Stats:
        def read() -> Stats:
            with self._process.oneshot():
                cpu = self._process.cpu_percent(None)
                memory = self._process.memory_info().rss
            net = psutil.net_io_counters()
            return Stats(
                cpu_percent=cpu,
                memory_used=memory,
                memory_limit=psutil.virtual_memory().total,
                network_rx=net.bytes_recv,
                network_tx=net.bytes_sent,
            )

        return await asyncio.to_thread(read)

    async def logs(
        self, instance: str, tail: int = 200, since: datetime | None = None
    ) -> list[LogLine]:
        return []

    async def follow(self, instance: str) -> AsyncIterator[LogLine]:
        return
        yield  # an async generator that ends at once

    async def disk(self) -> DiskUsage:
        return DiskUsage()

    async def host(self) -> Host:
        memory, disk = await asyncio.gather(
            asyncio.to_thread(psutil.virtual_memory),
            asyncio.to_thread(psutil.disk_usage, "/"),
        )
        return Host(
            cpus=psutil.cpu_count() or 1,
            memory=memory.total,
            docker_version=None,
            disk_total=disk.total,
            disk_free=disk.free,
        )


_runtime: Runtime | None = None


def set_runtime(backend: Runtime | None) -> None:
    """Install a backend (tests, a swap); None rediscovers on next use."""
    global _runtime
    _runtime = backend


def _discover() -> Runtime:
    """The deploy component's backend when the stack has it, else this
    process."""
    try:
        module = import_module(BACKEND_MODULE)
    except ModuleNotFoundError as error:
        # Only the deploy component being absent falls back; a broken
        # import inside it must surface.
        if error.name is None or not BACKEND_MODULE.startswith(error.name):
            raise
        return ProcessRuntime()
    backend: Runtime = module.create()
    return backend


def get_runtime() -> Runtime:
    """The installed backend, discovered on first use."""
    global _runtime
    backend = _runtime
    if backend is None:
        backend = _runtime = _discover()
    return backend


async def services() -> list[Service]:
    return await get_runtime().services()


async def stats(instance: str) -> Stats:
    return await get_runtime().stats(instance)


async def logs(
    instance: str, tail: int = 200, since: datetime | None = None
) -> list[LogLine]:
    return await get_runtime().logs(instance, tail=tail, since=since)


def follow(instance: str) -> AsyncIterator[LogLine]:
    return get_runtime().follow(instance)


async def disk() -> DiskUsage:
    return await get_runtime().disk()


async def host() -> Host:
    return await get_runtime().host()
