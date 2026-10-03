"""A runtime backend for tests (``app.core.runtime``): fixed services and
stats, installed with ``use_runtime(monkeypatch, ...)`` and put back after."""

from datetime import timedelta

import pytest

from app.core import runtime
from app.core.runtime import Instance, RuntimeUnavailableError, Service, Stats
from app.core.time import utcnow

MiB = 2**20
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
    """The services a stack runs, and the same stats for every instance."""

    def __init__(
        self, *instances: Instance, backend_name: str = "docker", fail: bool = False
    ) -> None:
        self.backend_name = backend_name
        self._instances = instances
        self._fail = fail
        self.asked: list[str] = []
        self.listed = 0

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


def use_runtime(monkeypatch: pytest.MonkeyPatch, fake: FakeRuntime) -> FakeRuntime:
    monkeypatch.setattr(runtime, "_runtime", fake)
    return fake
