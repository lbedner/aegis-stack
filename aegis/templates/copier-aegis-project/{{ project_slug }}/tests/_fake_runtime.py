"""A runtime backend for tests (``app.core.runtime``): fixed services,
stats and log lines, installed with ``use_runtime(monkeypatch, ...)`` and
put back after."""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import pytest

from app.core import runtime
from app.core.constants import ComponentName
from app.core.runtime import (
    Host,
    Instance,
    LogLine,
    RuntimeUnavailableError,
    Service,
    Stats,
)
from app.core.time import utcnow
from app.services.system import health_probes, load_cost
from app.services.system.models import ComponentStatus, LoadCosts

MiB = 2**20
GiB = 2**30
WORKER = Instance(
    id="w1",
    name="app-worker-system-1",
    service="worker-system",
    state="running",
    health="healthy",
    restarts=2,
    started_at=utcnow() - timedelta(hours=3),
    image="app:latest",
    build="abc1234",
)
STOPPED = Instance(
    id="w2", name="app-worker-media-1", service="worker-media", state="exited"
)
REDIS = Instance(id="r1", name="app-redis-1", service="redis", state="running")
# Running while Docker's healthcheck on it fails.
UNHEALTHY = Instance(
    id="t1",
    name="app-traefik-1",
    service="traefik",
    state="running",
    health="unhealthy",
)
SERVER = Instance(
    id="s1",
    name="app-webserver-1",
    service="webserver",
    state="running",
    health="healthy",
    started_at=utcnow() - timedelta(hours=5),
    image="app:latest",
    build="abc1234",
)
HOST = Host(
    cpus=4,
    memory=8 * GiB,
    docker_version="27.1.1",
    disk_total=100 * GiB,
    disk_free=40 * GiB,
)
STATS = Stats(
    cpu_percent=12.5,
    memory_used=128 * MiB,
    memory_limit=512 * MiB,
    network_rx=2048,
    network_tx=1024,
    disk_read=4096,
    disk_write=0,
)


class FakeRuntime:
    """The services a stack runs, the same stats for every instance, and
    each instance's log lines (``lines``, read; ``followed``, followed)."""

    def __init__(
        self,
        *instances: Instance,
        backend_name: str = "docker",
        fail: bool = False,
        lines: dict[str, list[LogLine]] | None = None,
        followed: dict[str, list[LogLine]] | None = None,
    ) -> None:
        self.backend_name = backend_name
        self._instances = instances
        self._fail = fail
        self.asked: list[str] = []
        self.listed = 0
        self.lines = lines or {}
        self.followed = followed or {}
        # (instance, tail, since) for each logs read
        self.logged: list[tuple[str, int, datetime | None]] = []
        self.restarted: list[str] = []

    async def services(self) -> list[Service]:
        self.listed += 1
        if self._fail:
            raise RuntimeUnavailableError("the socket proxy is not answering")
        names = dict.fromkeys(i.service for i in self._instances)
        return [
            Service(name, [i for i in self._instances if i.service == name])
            for name in names
        ]

    async def stats(self, instance: str) -> Stats:
        self.asked.append(instance)
        return STATS

    async def logs(
        self, instance: str, tail: int = 200, since: datetime | None = None
    ) -> list[LogLine]:
        self.logged.append((instance, tail, since))
        return self.lines.get(instance, [])

    async def follow(self, instance: str) -> AsyncIterator[LogLine]:
        for line in self.followed.get(instance, []):
            yield line

    async def host(self) -> Host:
        if self._fail:
            raise RuntimeUnavailableError("the socket proxy is not answering")
        return HOST

    async def restart(self, instance: str) -> None:
        if self._fail:
            raise RuntimeUnavailableError("the socket proxy is not answering")
        self.restarted.append(instance)

    async def aclose(self) -> None:
        return None


def use_runtime(monkeypatch: pytest.MonkeyPatch, fake: FakeRuntime) -> FakeRuntime:
    monkeypatch.setattr(runtime, "_runtime", fake)
    return fake


def use_host_checks(
    monkeypatch: pytest.MonkeyPatch,
    memory_percent: float = 50.0,
    cpu_percent: float = 10.0,
) -> None:
    """The host's memory and CPU checks (``health_probes.host_metrics``) on
    ``HOST``, this much of each in use."""

    async def checks() -> dict[str, ComponentStatus]:
        total = HOST.memory / GiB
        return {
            "memory": ComponentStatus(
                name="memory",
                message="",
                metadata={
                    "percent_used": memory_percent,
                    "total_gb": total,
                    "available_gb": total * (1 - memory_percent / 100),
                },
            ),
            "cpu": ComponentStatus(
                name="cpu",
                message="",
                metadata={"percent_used": cpu_percent, "cpu_count": HOST.cpus},
            ),
        }

    monkeypatch.setattr(health_probes, "host_metrics", checks)


def use_load_costs(monkeypatch: pytest.MonkeyPatch, found: LoadCosts | None) -> None:
    """``load_cost.costs`` answering ``found`` (None: still measuring)."""

    async def costs() -> LoadCosts | None:
        return found

    monkeypatch.setattr(load_cost, "costs", costs)


def queue_status(name: str, message: str = "", **meta: Any) -> ComponentStatus:
    """A worker queue as its health check reports it: alive, idle, one
    consumer of ten slots, unless ``meta`` says otherwise."""
    base = {
        "worker_alive": True,
        "queued_jobs": 0,
        "jobs_ongoing": 0,
        "jobs_completed": 0,
        "jobs_failed": 0,
        "failure_rate_percent": 0.0,
        "consumer_count": 1,
        "max_concurrency": 10,
        "timeout_seconds": 300,
        "description": f"{name} jobs",
        "stream_name": f"taskiq:{name}",
    }
    return ComponentStatus(name=name, message=message, metadata=base | meta)


def worker_status(
    *queues: ComponentStatus, message: str = "", **meta: Any
) -> ComponentStatus:
    """The worker's health check with ``queues`` under it."""
    group = ComponentStatus(
        name="queues", message="", sub_components={q.name: q for q in queues}
    )
    return ComponentStatus(
        name=ComponentName.WORKER,
        message=message,
        metadata=meta,
        sub_components={"queues": group},
    )
