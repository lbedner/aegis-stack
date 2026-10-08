"""What each worker process runs with, checked against the settings.

The web process cannot see a worker's command line, and each engine has
its own defaults, so every worker reports what it was launched with next
to what ``Settings.WORKER_QUEUES`` asks for, and the Overseer compares.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.components.worker import runtime
from app.core.queue_workers import QueueWorker
from tests._fake_redis import FakeRedis


class TestLaunchSettings:
    def test_taskiq_flags(self) -> None:
        argv = [
            "taskiq",
            "worker",
            "q:broker",
            "--workers",
            "1",
            "--max-async-tasks=50",
        ]
        assert runtime.launch_settings("taskiq", argv) == {
            "processes": 1,
            "concurrency": 50,
        }

    def test_dramatiq_flags(self) -> None:
        argv = ["dramatiq", "app.broker", "app.q", "-p", "2", "--threads", "15"]
        assert runtime.launch_settings("dramatiq", argv) == {
            "processes": 2,
            "concurrency": 15,
        }

    def test_flags_left_out_are_the_engines_defaults(self) -> None:
        assert runtime.launch_settings("taskiq", ["taskiq", "worker", "q"]) == {
            "processes": 2,
            "concurrency": 100,
        }


class TestConfigured:
    def test_a_listed_queue_names_its_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            runtime.settings,
            "WORKER_QUEUES",
            {"load_test": QueueWorker(concurrency=50)},
        )
        assert runtime.configured("load_test") == (50, "WORKER_QUEUES[load_test]")

    def test_other_queues_name_the_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runtime.settings, "WORKER_QUEUES", {})
        monkeypatch.setattr(
            runtime.settings, "WORKER_QUEUE_DEFAULT", QueueWorker(concurrency=7)
        )
        assert runtime.configured("media") == (7, "WORKER_QUEUE_DEFAULT")


class TestDiscoveryCheck:
    def test_names_that_match_no_queue(self) -> None:
        found = runtime.unknown_queues(["system", "sytem"], ["system", "load_test"])
        assert found == ["sytem"]

    def test_a_worker_will_not_start_on_a_misnamed_queue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            runtime.settings, "WORKER_QUEUES", {"sytem": QueueWorker(concurrency=5)}
        )
        with pytest.raises(SystemExit, match="sytem"):
            runtime.check_queues()

    def test_the_shipped_queues_pass(self) -> None:
        runtime.check_queues()

    def test_the_entrypoint_can_ask_a_queues_concurrency(self) -> None:
        """``scripts/entrypoint.sh`` runs this module first, before anything
        else is imported, so its imports must not loop back into it."""
        import subprocess
        import sys

        done = subprocess.run(
            [sys.executable, "-m", "app.components.worker.runtime", "concurrency", "system"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr
        assert done.stdout.strip().isdigit()


def _report(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "worker": "host:42",
        "queue": "load_test",
        "engine": "taskiq",
        "version": "0.12.6",
        "processes": 1,
        "concurrency": 50,
    }
    return runtime.report(**(fields | overrides))


class TestReports:
    def test_a_report_holds_what_runs_and_what_was_asked_for(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            runtime.settings,
            "WORKER_QUEUES",
            {"load_test": QueueWorker(concurrency=50)},
        )
        report = _report(concurrency=100)
        assert report["concurrency"] == 100
        assert report["configured"] == 50
        assert report["source"] == "WORKER_QUEUES[load_test]"

    @pytest.mark.asyncio
    async def test_a_published_report_reads_back_and_expires(self) -> None:
        redis = FakeRedis()
        await runtime.publish_runtime(redis, _report())
        key = runtime.runtime_key("host:42")
        assert redis.ttl[key] == runtime.RUNTIME_TTL_SECONDS
        (back,) = await runtime.read_runtime(redis)
        assert back["worker"] == "host:42" and back["concurrency"] == "50"

    def test_the_report_keys_are_declared_for_the_keyspace_map(self) -> None:
        from fnmatch import fnmatchcase

        patterns = [f.pattern for f in runtime.REDIS_KEYS]
        assert any(fnmatchcase(runtime.runtime_key("host:42"), p) for p in patterns)


@pytest.mark.asyncio
async def test_publishing_never_breaks_the_worker() -> None:
    redis = AsyncMock()
    redis.hset.side_effect = ConnectionError("Redis down")
    await runtime.publish_runtime(redis, {"worker": "w"})


def test_the_sync_twin_never_breaks_the_worker_either() -> None:
    """Dramatiq's hooks are synchronous."""

    class Down:
        def hset(self, *_a: Any, **_k: Any) -> None:
            raise ConnectionError("Redis down")

    runtime.publish_runtime_sync(Down(), {"worker": "w"})
