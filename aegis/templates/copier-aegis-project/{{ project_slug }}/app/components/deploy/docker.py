"""The Docker backend of ``app.core.runtime``, read through the socket proxy.

The webserver never holds the Docker socket. The ``socket-proxy`` service
does, and answers a short list of reads on its own Unix socket in the
``docker-proxy`` volume; this talks to that with the ``httpx`` the app
already has. Everything is scoped to this compose project by the
``com.docker.compose.project`` label, so other projects on the same host
are never listed.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import json
import os
import re
import socket
import time
from typing import Any

import httpx
import psutil

from app.core.runtime import (
    DiskUsage,
    Host,
    Instance,
    LogLine,
    RuntimeUnavailableError,
    Service,
    Stats,
)
from app.core.time import utcnow

from .docker_logs import follow as follow_logs
from .docker_logs import history

PROXY_SOCKET = "/var/run/docker-proxy/docker.sock"
PROJECT_LABEL = "com.docker.compose.project"
SERVICE_LABEL = "com.docker.compose.service"
# Stamped by the Dockerfile from the BUILD_ID build arg.
BUILD_LABEL = "org.opencontainers.image.revision"
TIMEOUT = httpx.Timeout(10.0)
# ``/system/df`` sizes every layer and volume; it can take a while.
DISK_TIMEOUT = httpx.Timeout(60.0)
# Docker waits up to 10 s for a container to stop before killing it.
RESTART_TIMEOUT = httpx.Timeout(30.0)
# Docker's humanized duration in the list's ``Status`` ("Up 5 hours").
_UNIT_SECONDS = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
    "month": 2592000,
    "year": 31536000,
}
_UP = re.compile(
    r"^Up (?:(Less than a second)|About an? (minute|hour)"
    r"|(\d+) (second|minute|hour|day|week|month|year)s?)"
)
_HEALTH = re.compile(r"\((?:health: )?(healthy|unhealthy|starting)\)")


def parse_status(status: str) -> tuple[int | None, str | None]:
    """Uptime in seconds and health, from the list's ``Status``
    (``Up 5 hours (healthy)``); uptime is None when not running.

    Inspect would give the exact start time and the restart count, but it
    also returns the container's whole environment, so the proxy refuses
    it. The cost: uptime is only as precise as Docker's humanized duration
    (rounded to the unit shown: "5 hours", "About a minute", "2 weeks"),
    and there is no restart count at all.
    """
    health = _HEALTH.search(status)
    match = _UP.match(status)
    if match is None:
        return None, health.group(1) if health else None
    less, about, count, unit = match.groups()
    if less:
        uptime = 0
    elif about:
        uptime = _UNIT_SECONDS[about]
    else:
        uptime = int(count) * _UNIT_SECONDS[unit]
    return uptime, health.group(1) if health else None


def _instance(summary: dict[str, Any]) -> Instance:
    """One container, from the list alone (see ``parse_status``)."""
    labels = summary.get("Labels") or {}
    short_id = summary["Id"][:12]
    names = summary.get("Names") or []
    uptime, health = parse_status(summary.get("Status") or "")
    return Instance(
        id=short_id,
        name=names[0].lstrip("/") if names else short_id,
        service=labels.get(SERVICE_LABEL, ""),
        state=summary.get("State") or "unknown",
        health=health,
        restarts=None,
        started_at=None if uptime is None else utcnow() - timedelta(seconds=uptime),
        image=summary.get("Image"),
        build=labels.get(BUILD_LABEL)
        or str(summary.get("ImageID", "")).removeprefix("sha256:")[:12]
        or None,
    )


# The shortest stretch a CPU share is measured over: just under the
# containers sampler's one-second tick, so each tick measures afresh.
MIN_CPU_WINDOW = 0.9


@dataclass(frozen=True)
class _CpuBaseline:
    reading: tuple[int, int]
    at: float
    percent: float | None


def _cpu_reading(cpu: dict[str, Any]) -> tuple[int, int]:
    """(the container's CPU time, the host's) in one sample."""
    return (cpu.get("cpu_usage") or {}).get("total_usage", 0), cpu.get(
        "system_cpu_usage", 0
    )


def _stats(data: dict[str, Any], before: tuple[int, int] | None) -> Stats:
    """The numbers ``docker stats`` shows, from one Engine API sample; CPU
    is the share used since ``before`` (None without one)."""
    cpu = data.get("cpu_stats") or {}
    online = cpu.get("online_cpus") or 1
    percent = None
    if before is not None:
        now = _cpu_reading(cpu)
        cpu_delta, system_delta = now[0] - before[0], now[1] - before[1]
        percent = (
            cpu_delta / system_delta * online * 100.0
            if cpu_delta > 0 and system_delta > 0
            else 0.0
        )
    memory = data.get("memory_stats") or {}
    extra = memory.get("stats") or {}
    # Page cache the kernel can drop is not "used" (cgroup v2, then v1).
    cache = extra.get("inactive_file", extra.get("total_inactive_file", 0))
    networks = list((data.get("networks") or {}).values())
    io = (data.get("blkio_stats") or {}).get("io_service_bytes_recursive") or []
    return Stats(
        cpu_percent=percent,
        memory_used=max(int(memory.get("usage", 0)) - int(cache), 0),
        memory_limit=memory.get("limit") or None,
        cpus=online,
        network_rx=sum(int(n.get("rx_bytes", 0)) for n in networks),
        network_tx=sum(int(n.get("tx_bytes", 0)) for n in networks),
        disk_read=sum(int(e["value"]) for e in io if e.get("op", "").lower() == "read"),
        disk_write=sum(
            int(e["value"]) for e in io if e.get("op", "").lower() == "write"
        ),
    )


def _unix_seconds(value: datetime) -> str:
    """A naive value is UTC, the app's storage convention."""
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return str(int(aware.timestamp()))


class DockerRuntime:
    """Containers of this compose project, through the proxy socket."""

    backend_name = "docker"

    def __init__(
        self,
        *,
        socket_path: str = PROXY_SOCKET,
        project: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._socket = socket_path
        self._project = project or os.environ.get("COMPOSE_PROJECT_NAME") or None
        self._transport = transport
        # Each container's CPU baseline: the reading the next share is
        # measured from, when it was taken, and the share it gave.
        # ponytail: per process and never pruned; a recreated container
        # leaves one stale entry behind.
        self._cpu: dict[str, _CpuBaseline] = {}
        self._http: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        """The one client every call shares: a connection pool to the proxy
        socket, made on first use and closed by ``aclose`` at shutdown."""
        if self._http is None:
            transport = self._transport or httpx.AsyncHTTPTransport(uds=self._socket)
            self._http = httpx.AsyncClient(
                transport=transport, base_url="http://docker", timeout=TIMEOUT
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _get(
        self,
        client: httpx.AsyncClient,
        path: str,
        timeout: httpx.Timeout = TIMEOUT,
        **params: str,
    ) -> httpx.Response:
        return await self._request(client, "GET", path, timeout, **params)

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        timeout: httpx.Timeout = TIMEOUT,
        **params: str,
    ) -> httpx.Response:
        """One call through the proxy; anything but a success (a path the
        proxy refuses included) is ``RuntimeUnavailableError``."""
        try:
            response = await client.request(
                method, path, params=params, timeout=timeout
            )
        except httpx.TransportError as error:
            raise RuntimeUnavailableError(
                f"Docker socket proxy unreachable at {self._socket}: {error}"
            ) from error
        if not response.is_success:
            raise RuntimeUnavailableError(
                f"Docker answered {path} with {response.status_code}: "
                f"{response.text[:200]}"
            )
        return response

    async def _list(
        self, client: httpx.AsyncClient, filters: dict[str, list[str]]
    ) -> list[dict[str, Any]]:
        response = await self._get(
            client, "/containers/json", all="true", filters=json.dumps(filters)
        )
        return response.json()

    async def _project_name(self, client: httpx.AsyncClient) -> str:
        """This container's compose project, from its own row in the list
        (the container's hostname is its id unless compose sets one)."""
        if self._project is None:
            mine = await self._list(client, {"id": [socket.gethostname()]})
            project = (mine[0].get("Labels") or {}).get(PROJECT_LABEL) if mine else None
            if not project:
                raise RuntimeUnavailableError(
                    "This container is not part of a compose project"
                )
            self._project = project
        return self._project

    async def services(self) -> list[Service]:
        client = self._client()
        project = await self._project_name(client)
        listed = await self._list(client, {"label": [f"{PROJECT_LABEL}={project}"]})
        grouped: dict[str, list[Instance]] = {}
        for summary in listed:
            instance = _instance(summary)
            grouped.setdefault(instance.service, []).append(instance)
        return [
            Service(name=name, instances=sorted(found, key=lambda i: i.name))
            for name, found in sorted(grouped.items())
        ]

    async def stats(self, instance: str) -> Stats:
        """One sample, read at once (``one-shot``): Docker otherwise waits a
        second for a second one. CPU is measured against this container's
        previous read, or Docker's own previous sample when it sends one."""
        response = await self._get(
            self._client(),
            f"/containers/{instance}/stats",
            stream="false",
            **{"one-shot": "true"},
        )
        data = response.json()
        docker_before = _cpu_reading(data.get("precpu_stats") or {})
        if docker_before[1]:
            return _stats(data, docker_before)
        return self._measured(instance, data)

    def _measured(self, instance: str, data: dict[str, Any]) -> Stats:
        """CPU against this container's baseline, which moves only after
        ``MIN_CPU_WINDOW``: two readers in step (the sampler and a viewer)
        would otherwise measure a fraction of a second, which is noise."""
        now = time.monotonic()
        base = self._cpu.get(instance)
        if base is not None and now - base.at < MIN_CPU_WINDOW:
            return replace(_stats(data, None), cpu_percent=base.percent)
        stats = _stats(data, base.reading if base else None)
        reading = _cpu_reading(data.get("cpu_stats") or {})
        self._cpu[instance] = _CpuBaseline(reading, now, stats.cpu_percent)
        return stats

    @staticmethod
    def _log_params(tail: str, since: datetime | None = None) -> dict[str, str]:
        params = {"stdout": "1", "stderr": "1", "timestamps": "1", "tail": tail}
        if since is not None:
            params["since"] = _unix_seconds(since)
        return params

    async def logs(
        self, instance: str, tail: int = 200, since: datetime | None = None
    ) -> list[LogLine]:
        response = await self._get(
            self._client(),
            f"/containers/{instance}/logs",
            **self._log_params(str(tail), since),
        )
        return history(response.content)

    async def follow(
        self, instance: str, since: datetime | None = None
    ) -> AsyncIterator[LogLine]:
        """New lines as the container writes them, until the caller stops."""
        params = {**self._log_params("all" if since else "0", since), "follow": "1"}
        async for line in follow_logs(self._client(), instance, params, self._socket):
            yield line

    async def restart(self, instance: str) -> None:
        """Restart one container: the one write the proxy allows."""
        await self._request(
            self._client(), "POST", f"/containers/{instance}/restart", RESTART_TIMEOUT
        )

    async def disk(self) -> DiskUsage:
        client = self._client()
        project = await self._project_name(client)
        data = (await self._get(client, "/system/df", timeout=DISK_TIMEOUT)).json()

        def mine(labels: dict[str, str] | None) -> bool:
            return (labels or {}).get(PROJECT_LABEL) == project

        containers = {
            (c.get("Names") or [c["Id"]])[0].lstrip("/"): int(c.get("SizeRw") or 0)
            for c in data.get("Containers") or []
            if mine(c.get("Labels"))
        }
        volumes = {
            v["Name"]: max(int((v.get("UsageData") or {}).get("Size") or 0), 0)
            for v in data.get("Volumes") or []
            if mine(v.get("Labels"))
        }
        return DiskUsage(containers=containers, volumes=volumes)

    async def host(self) -> Host:
        """The Docker host. Disk is the filesystem this container's root
        sits on, which is the one Docker keeps its images and volumes on."""
        info = (await self._get(self._client(), "/info")).json()
        usage = await asyncio.to_thread(psutil.disk_usage, "/")
        return Host(
            cpus=int(info.get("NCPU") or 1),
            memory=int(info.get("MemTotal") or 0),
            docker_version=info.get("ServerVersion"),
            disk_total=usage.total,
            disk_free=usage.free,
        )


def create() -> DockerRuntime:
    """What ``app.core.runtime`` installs when this component is present."""
    return DockerRuntime()
