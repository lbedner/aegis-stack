"""Background collection and failover with real Redis and deterministic input."""

import asyncio
from datetime import UTC, datetime

import pytest

from app.components.backend.error_tracking import collector
from app.core import runtime
from app.core.runtime import Instance, parse_log_line
from app.services.system.errors.store import ErrorStore
from tests._fake_runtime import FakeRuntime


async def wait_count(repository: ErrorStore, count: int) -> None:
    async with asyncio.timeout(5):
        while await repository.client.hlen(repository.key("records")) != count:
            await asyncio.sleep(0.02)


async def test_closed_browser_collection_and_fenced_failover(
    store: ErrorStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = Instance("id", "server", "webserver", "running")
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S") + ".123456789Z "
    lines = [
        parse_log_line(stamp + raw, "stderr")
        for raw in (
            "ERROR: failed",
            "Traceback (most recent call last):",
            '  File "/code/app/run.py", line 1, in run',
            "ValueError: failed",
            "ERROR: failed",
            "Traceback (most recent call last):",
            '  File "/code/app/run.py", line 1, in run',
            "ValueError: failed",
        )
    ]
    monkeypatch.setattr(
        runtime, "_runtime", FakeRuntime(instance, followed={"id": lines})
    )
    monkeypatch.setattr(collector, "TICK", 0.05)
    owners = [collector.Collector(store), collector.Collector(store)]
    tasks = [asyncio.create_task(owner.run()) for owner in owners]
    try:
        await wait_count(store, 2)
        active = await store.client.get(store.key("lease"))
        winner = next(i for i, o in enumerate(owners) if o.token.encode() == active)
        assert (await store.issues())[0].count == 2
        tasks[winner].cancel()
        await asyncio.gather(tasks[winner], return_exceptions=True)
        async with asyncio.timeout(5):
            while await store.client.get(
                store.key("lease")
            ) == active or not await store.client.get(store.key("lease")):
                await asyncio.sleep(0.02)
        await asyncio.sleep(0.1)
        assert (await store.issues())[0].count == 2
        assert (
            await store.insert(
                (await store.occurrences((await store.issues())[0].fingerprint))[0][0],
                token=owners[winner].token,
            )
            == "fenced"
        )
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert await store.client.get(store.key("lease")) is None
    assert not any(owner.pumps for owner in owners)


async def test_real_docker_history_live_replay_and_replacement(
    store: ErrorStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opt-in: disposable containers only; never restart the user's services."""
    import json
    import os
    from pathlib import Path
    import subprocess
    from uuid import uuid4

    if os.environ.get("AEGIS_ERROR_TRACKING_DOCKER_TEST") != "1":
        pytest.skip(
            "Set AEGIS_ERROR_TRACKING_DOCKER_TEST=1 for real Docker integration"
        )
    docker = pytest.importorskip("app.components.deploy.docker")
    project = "errors-test-" + uuid4().hex[:10]
    host = subprocess.check_output(
        ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
        text=True,
    ).strip()
    socket = host.removeprefix("unix://")
    if not Path(socket).exists():
        pytest.skip("Docker Unix socket is unavailable")
    backend = docker.DockerRuntime(socket_path=socket, project=project)
    monkeypatch.setattr(runtime, "_runtime", backend)
    monkeypatch.setattr(collector, "TICK", 0.1)
    store.max_occurrences = 20
    trace = 'Traceback (most recent call last):\n  File "/code/app/demo.py", line 1, in run\nValueError: test failure'
    payload = json.dumps(
        {"event": "integration JSON failure", "level": "error", "exception": trace}
    )
    script = (
        "import time; print("
        + repr(payload)
        + "); print("
        + repr(payload)
        + "); print("
        + repr(trace)
        + "); print('ERROR: integration message only'); time.sleep(120)"
    )
    containers: list[str] = []
    tasks: list[asyncio.Task[None]] = []

    def launch(service: str) -> str:
        identity = subprocess.check_output(
            [
                "docker",
                "run",
                "-d",
                "--pull=never",
                "--label",
                "com.docker.compose.project=" + project,
                "--label",
                "com.docker.compose.service=" + service,
                "python:3.14-slim",
                "python",
                "-u",
                "-c",
                script,
            ],
            text=True,
        ).strip()
        containers.append(identity)
        return identity

    try:
        launch("webserver")
        worker = launch("worker-system")
        first = collector.Collector(store)
        tasks.append(asyncio.create_task(first.run()))
        await wait_count(store, 8)
        issues = await store.issues()
        assert len(issues) == 4 and sorted(issue.count for issue in issues) == [
            1,
            1,
            3,
            3,
        ]
        traced = [issue for issue in issues if issue.count == 3]
        assert (await store.detail(traced[0].latest_id)).traceback == trace
        tasks[0].cancel()
        await asyncio.gather(tasks[0], return_exceptions=True)
        second = collector.Collector(store)
        tasks.append(asyncio.create_task(second.run()))
        await asyncio.sleep(1)
        assert await store.client.hlen(store.key("records")) == 8
        subprocess.run(["docker", "rm", "-f", worker], check=True, capture_output=True)
        containers.remove(worker)
        launch("worker-system")
        await wait_count(store, 12)
        assert max(issue.count for issue in await store.issues()) == 6
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await backend.aclose()
        for identity in containers:
            subprocess.run(
                ["docker", "rm", "-f", identity], check=False, capture_output=True
            )


async def test_real_redis_outage_and_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os
    import subprocess
    from uuid import uuid4

    if os.environ.get("AEGIS_ERROR_TRACKING_DOCKER_TEST") != "1":
        pytest.skip(
            "Set AEGIS_ERROR_TRACKING_DOCKER_TEST=1 for isolated Redis outage test"
        )
    redis = pytest.importorskip("redis.asyncio")
    import socket

    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        fixed_port = reservation.getsockname()[1]
    identity = subprocess.check_output(
        [
            "docker",
            "run",
            "-d",
            "--pull=never",
            "-p",
            f"127.0.0.1:{fixed_port}:6379",
            "redis:7-alpine",
            "redis-server",
            "--save",
            "",
            "--appendonly",
            "no",
        ],
        text=True,
    ).strip()
    client = None
    task = None
    try:
        port = subprocess.check_output(
            [
                "docker",
                "inspect",
                "--format",
                '{{(index (index .NetworkSettings.Ports "6379/tcp") 0).HostPort}}',
                identity,
            ],
            text=True,
        ).strip()
        client = redis.from_url(
            "redis://127.0.0.1:" + port, socket_connect_timeout=0.2, socket_timeout=0.2
        )
        repository = ErrorStore(
            client, "outage-" + uuid4().hex, max_occurrences=10, retention_seconds=60
        )
        instance = Instance("outage-id", "server", "webserver", "running")
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S") + ".123456789Z "
        lines = [parse_log_line(stamp + "ERROR: outage test", "stderr")]
        monkeypatch.setattr(
            runtime, "_runtime", FakeRuntime(instance, followed={instance.id: lines})
        )
        monkeypatch.setattr(collector, "TICK", 0.05)
        owner = collector.Collector(repository)
        task = asyncio.create_task(owner.run())
        await wait_count(repository, 1)
        subprocess.run(
            ["docker", "stop", "-t", "1", identity], check=True, capture_output=True
        )
        async with asyncio.timeout(4):
            while owner.pumps:
                await asyncio.sleep(0.05)
        subprocess.run(["docker", "start", identity], check=True, capture_output=True)
        async with asyncio.timeout(12):
            while True:
                try:
                    if await repository.client.hlen(repository.key("records")) == 1:
                        break
                except redis.ConnectionError:
                    pass
                await asyncio.sleep(0.05)
        assert (await repository.issues())[0].count == 1
    finally:
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if client:
            await client.aclose()
        subprocess.run(
            ["docker", "rm", "-f", identity], check=False, capture_output=True
        )
