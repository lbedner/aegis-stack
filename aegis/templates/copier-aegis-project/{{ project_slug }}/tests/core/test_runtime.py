"""What is running and how it is doing, behind one interface.

Every project has ``app.core.runtime``. Without a deploy target the
backend is the app's own process (psutil), so pages that read it render
anywhere; the deploy component swaps in the Docker backend.
"""

from datetime import datetime

import pytest

from app.core import runtime
from app.core.runtime import ProcessRuntime, page_for, parse_log_line


@pytest.mark.parametrize(
    ("service", "page"),
    [
        ("webserver", "server"),
        ("worker-system", "worker"),
        ("worker-load-test", "worker"),
        ("scheduler", "scheduler"),
        ("redis", "redis"),
        ("postgres", "database"),
        ("seaweedfs", "storage"),
        ("traefik", "ingress"),
        ("ollama", "inference"),
        ("socket-proxy", None),
    ],
)
def test_each_compose_service_maps_to_its_overseer_page(
    service: str, page: str | None
) -> None:
    assert page_for(service) == page


class TestLogLines:
    def test_a_json_line_gives_its_level_and_event(self) -> None:
        line = parse_log_line(
            '2026-10-02T20:45:39.637123456Z {"level": "warning", "event": "slow"}',
            "stdout",
        )
        assert line.timestamp == datetime(2026, 10, 2, 20, 45, 39, 637123)
        assert line.level == "warning"
        assert line.event == "slow"
        assert line.stream == "stdout"

    def test_a_console_line_loses_its_colour_codes(self) -> None:
        line = parse_log_line(
            "2026-10-02T20:45:39Z \x1b[2m12:00\x1b[0m [\x1b[32minfo\x1b[0m] started",
            "stderr",
        )
        assert line.text == "12:00 [info] started"
        assert line.level is None
        assert line.stream == "stderr"

    def test_a_line_without_a_timestamp_keeps_its_text(self) -> None:
        line = parse_log_line("plain text", "stdout")
        assert line.timestamp is None
        assert line.text == "plain text"

    def test_a_json_array_is_just_text(self) -> None:
        line = parse_log_line("[1, 2]", "stdout")
        assert line.event is None
        assert line.text == "[1, 2]"


class TestProcessRuntime:
    """The backend with no deploy target: the app's own process."""

    async def test_services_is_this_process(self) -> None:
        (service,) = await ProcessRuntime().services()
        (instance,) = service.instances
        assert instance.state == "running"
        assert instance.started_at is not None
        assert instance.uptime_seconds is not None and instance.uptime_seconds >= 0

    async def test_stats_and_host_read_the_machine(self) -> None:
        backend = ProcessRuntime()
        (service,) = await backend.services()
        stats = await backend.stats(service.instances[0].id)
        assert stats.memory_used > 0
        host = await backend.host()
        assert host.cpus >= 1
        assert host.memory > 0
        assert host.docker_version is None

    async def test_there_are_no_container_logs(self) -> None:
        backend = ProcessRuntime()
        assert await backend.logs("self") == []
        assert [line async for line in backend.follow("self")] == []


class TestDiscovery:
    def test_no_deploy_component_means_the_process_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runtime, "BACKEND_MODULE", "app.components.absent")
        runtime.set_runtime(None)
        try:
            assert isinstance(runtime.get_runtime(), ProcessRuntime)
        finally:
            runtime.set_runtime(None)

    async def test_the_module_calls_use_the_installed_backend(self) -> None:
        runtime.set_runtime(ProcessRuntime())
        try:
            (service,) = await runtime.services()
            assert service.instances
        finally:
            runtime.set_runtime(None)
