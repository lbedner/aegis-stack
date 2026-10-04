"""The Docker backend of ``app.core.runtime``, read through the socket proxy.

Driven by ``httpx.MockTransport`` with the Engine API's own shapes, so
no daemon is needed. Scoping is by the ``com.docker.compose.project``
label: another project's containers on the same host are never listed.
"""

import json
import re
from typing import Any

import httpx
import pytest

from app.components.deploy import docker
from app.components.deploy.docker import (
    BUILD_LABEL,
    DockerRuntime,
    parse_status,
)
from app.components.deploy.docker_logs import split_frames
from app.core import runtime
from app.core.runtime import RuntimeUnavailableError

PROJECT = "demo"


def _container(cid: str, service: str, project: str = PROJECT) -> dict[str, Any]:
    return {
        "Id": cid * 8,
        "Names": [f"/{project}-{service}-1"],
        "Image": f"{project}:latest",
        "ImageID": "sha256:" + "ab" * 32,
        "State": "running",
        "Status": "Up 5 hours (healthy)",
        "Created": 1_790_960_104,
        "Labels": {
            "com.docker.compose.project": project,
            "com.docker.compose.service": service,
            BUILD_LABEL: "abc1234",
        },
    }


# Every path the backend asked for, so a test can prove inspect is never one.
REQUESTED: list[str] = []
STATS_ASKED: list[dict[str, str]] = []
# One-shot samples to answer with, in order (STATS once they run out).
SAMPLES: list[dict[str, Any]] = []
INSPECT = re.compile(r"^(/v[\d.]+)?/containers/(?!json$)[^/]+/json$")


def _frame(stream: int, text: str) -> bytes:
    payload = text.encode()
    return bytes([stream, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload


STATS = {
    "cpu_stats": {
        "cpu_usage": {"total_usage": 3_000_000},
        "system_cpu_usage": 20_000_000,
        "online_cpus": 2,
    },
    "precpu_stats": {
        "cpu_usage": {"total_usage": 1_000_000},
        "system_cpu_usage": 10_000_000,
    },
    "memory_stats": {
        "usage": 120_000_000,
        "limit": 805_306_368,
        "stats": {"inactive_file": 20_000_000},
    },
    "networks": {
        "eth0": {"rx_bytes": 100, "tx_bytes": 50},
        "eth1": {"rx_bytes": 1, "tx_bytes": 2},
    },
    "blkio_stats": {
        "io_service_bytes_recursive": [
            {"op": "read", "value": 4096},
            {"op": "write", "value": 8192},
        ]
    },
}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    REQUESTED.append(path)
    if path == "/containers/json":
        filters = json.loads(request.url.params["filters"])
        if "id" in filters:
            return httpx.Response(200, json=[_container("a", "webserver")])
        assert filters == {"label": [f"com.docker.compose.project={PROJECT}"]}
        return httpx.Response(
            200,
            json=[_container("a", "webserver"), _container("b", "worker-system")],
        )
    if path.endswith("/stats"):
        STATS_ASKED.append(dict(request.url.params))
        return httpx.Response(200, json=SAMPLES.pop(0) if SAMPLES else STATS)
    if path.endswith("/logs"):
        body = _frame(
            1, '2026-10-02T20:45:39.5Z {"level": "error", "event": "boom"}\n'
        ) + _frame(2, "2026-10-02T20:45:40Z \x1b[31mred\x1b[0m\n")
        return httpx.Response(200, content=body)
    if path == "/system/df":
        return httpx.Response(
            200,
            json={
                "Containers": [
                    {**_container("a", "webserver"), "SizeRw": 10},
                    {**_container("c", "web", project="other"), "SizeRw": 99},
                ],
                "Volumes": [
                    {
                        "Name": f"{PROJECT}_storage-data",
                        "Labels": {"com.docker.compose.project": PROJECT},
                        "UsageData": {"Size": 2048},
                    },
                    {"Name": "stranger", "Labels": None, "UsageData": {"Size": 1}},
                ],
            },
        )
    if path == "/info":
        return httpx.Response(
            200, json={"NCPU": 4, "MemTotal": 8_000_000_000, "ServerVersion": "28.3.0"}
        )
    return httpx.Response(403, text="forbidden")


def _runtime() -> DockerRuntime:
    return DockerRuntime(project=PROJECT, transport=httpx.MockTransport(_handler))


def test_frames_split_by_stream() -> None:
    frames, rest = split_frames(_frame(1, "out\n") + _frame(2, "err\n") + b"\x01\x00")
    assert frames == [("stdout", b"out\n"), ("stderr", b"err\n")]
    assert rest == b"\x01\x00"


async def test_services_group_this_projects_containers() -> None:
    services = await _runtime().services()
    assert [s.name for s in services] == ["webserver", "worker-system"]
    assert [s.page for s in services] == ["server", "worker"]
    instance = services[0].instances[0]
    assert instance.name == "demo-webserver-1"
    assert (instance.state, instance.health) == ("running", "healthy")
    # The list does not carry a restart count; only inspect does.
    assert instance.restarts is None
    assert instance.build == "abc1234"
    assert instance.uptime_seconds == pytest.approx(5 * 3600, abs=5)


@pytest.mark.parametrize(
    ("status", "uptime", "health"),
    [
        ("Up 5 hours (healthy)", 5 * 3600, "healthy"),
        ("Up 46 hours (unhealthy)", 46 * 3600, "unhealthy"),
        ("Up 3 seconds (health: starting)", 3, "starting"),
        ("Up About a minute", 60, None),
        ("Up About an hour", 3600, None),
        ("Up Less than a second", 0, None),
        ("Up 2 weeks", 14 * 86400, None),
        ("Exited (0) 3 minutes ago", None, None),
        ("Restarting (1) 5 seconds ago", None, None),
    ],
)
def test_status_gives_coarse_uptime_and_health(
    status: str, uptime: int | None, health: str | None
) -> None:
    assert parse_status(status) == (uptime, health)


async def test_no_code_path_inspects_a_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inspect returns a container's whole Env and the proxy refuses it;
    discovery, listing, stats, logs, disk and host all do without it."""
    monkeypatch.setattr("socket.gethostname", lambda: "aaaaaaaaaaaa")
    REQUESTED.clear()
    backend = DockerRuntime(transport=httpx.MockTransport(_handler))
    await backend.services()
    await backend.stats("a")
    await backend.logs("a")
    _ = [line async for line in backend.follow("a")]
    await backend.disk()
    await backend.host()
    assert REQUESTED
    assert not [p for p in REQUESTED if INSPECT.match(p)], REQUESTED


async def test_the_project_comes_from_this_containers_own_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)
    monkeypatch.setattr("socket.gethostname", lambda: "aaaaaaaaaaaa")
    backend = DockerRuntime(transport=httpx.MockTransport(_handler))
    assert [s.name for s in await backend.services()] == ["webserver", "worker-system"]


async def test_stats_compute_cpu_and_memory_like_docker_stats() -> None:
    stats = await _runtime().stats("a")
    assert stats.cpu_percent == pytest.approx(40.0)
    assert stats.memory_used == 100_000_000
    assert stats.memory_limit == 805_306_368
    assert (stats.network_rx, stats.network_tx) == (101, 52)
    assert (stats.disk_read, stats.disk_write) == (4096, 8192)


def _one_shot(total: int, system: int) -> dict[str, Any]:
    """A sample as ``one-shot`` sends it: no previous reading alongside."""
    return {
        **STATS,
        "cpu_stats": {
            "cpu_usage": {"total_usage": total},
            "system_cpu_usage": system,
            "online_cpus": 2,
        },
        "precpu_stats": {"cpu_usage": {"total_usage": 0}, "system_cpu_usage": 0},
    }


async def test_stats_take_one_sample_and_cpu_from_the_last_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Docker's default stats call waits a second for a second sample; a
    one-shot read is immediate, so CPU comes from this read against the
    last one. The first read has nothing to compare with yet, and a read
    sooner than ``MIN_CPU_WINDOW`` after the last (the sampler and a viewer
    in step) gets the last share rather than a fraction of a second's."""
    clock = [0.0]
    monkeypatch.setattr(docker.time, "monotonic", lambda: clock[0])
    STATS_ASKED.clear()
    SAMPLES[:] = [
        _one_shot(1_000_000, 10_000_000),
        _one_shot(3_000_000, 20_000_000),
        _one_shot(3_000_100, 20_000_100),
    ]
    runtime = _runtime()
    first = await runtime.stats("a")
    clock[0] = 5.0
    second = await runtime.stats("a")
    clock[0] = 5.5
    soon_after = await runtime.stats("a")
    assert STATS_ASKED[0]["one-shot"] == "true"
    assert first.cpu_percent is None
    assert second.cpu_percent == pytest.approx(40.0)
    assert soon_after.cpu_percent == pytest.approx(40.0)
    assert first.memory_used == 100_000_000


async def test_the_backend_keeps_one_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """One connection pool to the proxy for every call, not a client (and a
    socket connection) per call; closed when the app shuts down."""
    made: list[int] = []

    class Counted(httpx.AsyncClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            made.append(1)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(docker.httpx, "AsyncClient", Counted)
    runtime = _runtime()
    await runtime.services()
    await runtime.stats("a")
    await runtime.logs("a")
    assert len(made) == 1
    await runtime.aclose()


async def test_logs_parse_both_streams() -> None:
    first, second = await _runtime().logs("a", tail=10)
    assert (first.stream, first.level, first.event) == ("stdout", "error", "boom")
    assert (second.stream, second.text) == ("stderr", "red")


async def test_follow_yields_the_same_lines() -> None:
    lines = [line async for line in _runtime().follow("a")]
    assert [line.stream for line in lines] == ["stdout", "stderr"]


async def test_tty_logs_are_raw_text() -> None:
    def tty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"2026-10-02T20:45:39Z one\ntwo")

    backend = DockerRuntime(project=PROJECT, transport=httpx.MockTransport(tty))
    assert [line.text for line in await backend.logs("a")] == ["one", "two"]


async def test_disk_is_scoped_to_the_project() -> None:
    disk = await _runtime().disk()
    assert disk.containers == {"demo-webserver-1": 10}
    assert disk.volumes == {f"{PROJECT}_storage-data": 2048}


async def test_host_comes_from_the_engine() -> None:
    host = await _runtime().host()
    assert (host.cpus, host.memory, host.docker_version) == (4, 8_000_000_000, "28.3.0")


async def test_a_refused_path_raises() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    backend = DockerRuntime(project=PROJECT, transport=httpx.MockTransport(refuse))
    with pytest.raises(RuntimeUnavailableError):
        await backend.host()


async def test_a_missing_socket_is_unavailable_not_a_crash(tmp_path: Any) -> None:
    backend = DockerRuntime(project=PROJECT, socket_path=str(tmp_path / "absent.sock"))
    with pytest.raises(RuntimeUnavailableError):
        await backend.services()


def test_the_deploy_component_installs_the_docker_backend() -> None:
    runtime.set_runtime(None)
    try:
        assert isinstance(runtime.get_runtime(), DockerRuntime)
    finally:
        runtime.set_runtime(None)
