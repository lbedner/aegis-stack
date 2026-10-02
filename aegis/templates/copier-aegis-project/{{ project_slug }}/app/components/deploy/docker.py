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
from datetime import UTC, datetime, timedelta
import json
import os
import re
import socket
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
    parse_log_line,
)
from app.core.time import utcnow

PROXY_SOCKET = "/var/run/docker-proxy/docker.sock"
PROJECT_LABEL = "com.docker.compose.project"
SERVICE_LABEL = "com.docker.compose.service"
# Stamped by the Dockerfile from the BUILD_ID build arg.
BUILD_LABEL = "org.opencontainers.image.revision"
TIMEOUT = httpx.Timeout(10.0)
# ``/system/df`` sizes every layer and volume; it can take a while.
DISK_TIMEOUT = httpx.Timeout(60.0)
_STREAMS = {0: "stdin", 1: "stdout", 2: "stderr"}
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


def split_frames(buffer: bytes) -> tuple[list[tuple[str, bytes]], bytes]:
    """Docker's multiplexed log stream: an 8-byte header (stream, three
    zero bytes, big-endian size) before each payload. Whole frames, and
    whatever is left for the next read."""
    frames: list[tuple[str, bytes]] = []
    while len(buffer) >= 8:
        size = int.from_bytes(buffer[4:8], "big")
        if len(buffer) < 8 + size:
            break
        frames.append((_STREAMS.get(buffer[0], "stdout"), buffer[8 : 8 + size]))
        buffer = buffer[8 + size :]
    return frames, buffer


def _multiplexed(head: bytes) -> bool:
    """A container without a TTY multiplexes stdout and stderr; one with a
    TTY (the workers set ``tty: true``) sends raw text."""
    return len(head) >= 4 and head[0] in _STREAMS and head[1:4] == b"\0\0\0"


def _decode(buffer: bytes, multiplexed: bool) -> tuple[list[LogLine], bytes]:
    """Complete lines out of ``buffer``, and the bytes still incomplete.

    ponytail: a line split across two multiplexed frames comes out as two
    lines; Docker writes one frame per write, so this needs a writer that
    flushes mid-line. Join per stream if it shows up.
    """
    if multiplexed:
        frames, rest = split_frames(buffer)
    else:
        text, newline, rest = buffer.rpartition(b"\n")
        frames = [("stdout", text)] if newline else []
    lines = [
        parse_log_line(line, stream)
        for stream, payload in frames
        for line in payload.decode(errors="replace").splitlines()
        if line.strip()
    ]
    return lines, rest


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


def _stats(data: dict[str, Any]) -> Stats:
    """The numbers ``docker stats`` shows, from one Engine API sample."""
    cpu = data.get("cpu_stats") or {}
    pre = data.get("precpu_stats") or {}
    cpu_delta = (cpu.get("cpu_usage") or {}).get("total_usage", 0) - (
        pre.get("cpu_usage") or {}
    ).get("total_usage", 0)
    system_delta = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
    online = cpu.get("online_cpus") or 1
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

    def _client(self, timeout: httpx.Timeout = TIMEOUT) -> httpx.AsyncClient:
        transport = self._transport or httpx.AsyncHTTPTransport(uds=self._socket)
        return httpx.AsyncClient(
            transport=transport, base_url="http://docker", timeout=timeout
        )

    async def _get(
        self, client: httpx.AsyncClient, path: str, **params: str
    ) -> httpx.Response:
        try:
            response = await client.get(path, params=params)
        except httpx.TransportError as error:
            raise RuntimeUnavailableError(
                f"Docker socket proxy unreachable at {self._socket}: {error}"
            ) from error
        if response.status_code != 200:
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
        async with self._client() as client:
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
        async with self._client() as client:
            response = await self._get(
                client, f"/containers/{instance}/stats", stream="false"
            )
        return _stats(response.json())

    @staticmethod
    def _log_params(tail: str, since: datetime | None = None) -> dict[str, str]:
        params = {"stdout": "1", "stderr": "1", "timestamps": "1", "tail": tail}
        if since is not None:
            params["since"] = _unix_seconds(since)
        return params

    async def logs(
        self, instance: str, tail: int = 200, since: datetime | None = None
    ) -> list[LogLine]:
        async with self._client() as client:
            response = await self._get(
                client,
                f"/containers/{instance}/logs",
                **self._log_params(str(tail), since),
            )
        body = response.content
        multiplexed = _multiplexed(body)
        lines, rest = _decode(body, multiplexed)
        if rest.strip() and not multiplexed:
            lines.append(parse_log_line(rest.decode(errors="replace"), "stdout"))
        return lines

    async def follow(self, instance: str) -> AsyncIterator[LogLine]:
        """New lines as the container writes them, until the caller stops."""
        params = {**self._log_params("0"), "follow": "1"}
        async with self._client(httpx.Timeout(10.0, read=None)) as client:
            try:
                async with client.stream(
                    "GET", f"/containers/{instance}/logs", params=params
                ) as response:
                    if response.status_code != 200:
                        raise RuntimeUnavailableError(
                            f"Docker refused logs for {instance}: "
                            f"{response.status_code}"
                        )
                    buffer, multiplexed = b"", None
                    async for chunk in response.aiter_bytes():
                        buffer += chunk
                        if multiplexed is None:
                            if len(buffer) < 4:
                                continue
                            multiplexed = _multiplexed(buffer)
                        lines, buffer = _decode(buffer, multiplexed)
                        for line in lines:
                            yield line
            except httpx.TransportError as error:
                raise RuntimeUnavailableError(
                    f"Docker socket proxy unreachable at {self._socket}: {error}"
                ) from error

    async def disk(self) -> DiskUsage:
        async with self._client(DISK_TIMEOUT) as client:
            project = await self._project_name(client)
            data = (await self._get(client, "/system/df")).json()

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
        async with self._client() as client:
            info = (await self._get(client, "/info")).json()
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
