"""A worker load test is sent by its caller and counted from task history.

No job runs it: a job sending the load competes with that load for the
worker, holds a slot in the queue it measures, and outlives its claim on a
long run, so it is redelivered and sends the whole load again.
"""

import asyncio
from typing import Any

import pytest

from app.components.worker.constants import LoadTestTypes, TaskNames
from app.components.worker.task_history.shared import _TASK_KEY_PREFIX
from app.services.load_test.worker import runs
from app.services.load_test.worker.models import LoadTestConfiguration
from tests._fake_redis import FakeRedis


def _config(**overrides: Any) -> LoadTestConfiguration:
    values: dict[str, Any] = {
        "num_tasks": 25,
        "task_type": LoadTestTypes.IO_SIMULATION,
        "batch_size": 10,
        "target_queue": "load_test",
    }
    return LoadTestConfiguration(**(values | overrides))


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    async def enqueue(task_name: str, queue: str) -> str:
        calls.append((task_name, queue))
        return f"job-{len(calls)}"

    monkeypatch.setattr(runs, "_enqueue", enqueue)
    return calls


def test_the_caller_sends_every_task_itself(sent: list[tuple[str, str]]) -> None:
    redis = FakeRedis()

    async def go() -> str:
        test_id = await runs.start(redis, _config())
        await runs.send(redis, test_id, _config())
        return test_id

    test_id = asyncio.run(go())

    assert sent == [(TaskNames.IO_SIMULATION_TASK, "load_test")] * 25
    progress = asyncio.run(runs.read(redis, test_id))
    assert progress is not None
    assert progress["tasks_sent"] == 25 and not progress["finished"]
    assert asyncio.run(runs.recent(redis, 5)) == [test_id]


def test_a_run_is_counted_from_its_tasks_records() -> None:
    run = {
        "config": _config(num_tasks=3).model_dump_json(),
        "started_at": "2026-10-08T10:00:00+00:00",
        "sent_at": "2026-10-08T10:00:01+00:00",
    }
    tasks = [
        {"status": "completed", "finished_at": "2026-10-08T10:00:04+00:00"},
        {"status": "failed", "finished_at": "2026-10-08T10:00:03+00:00"},
        {"status": "running"},
    ]

    progress = runs.tally("wlt_1", run, sent=3, tasks=tasks)

    assert progress["tasks_completed"] == 1 and progress["tasks_failed"] == 1
    assert not progress["finished"]

    tasks[2] = {"status": "completed", "finished_at": "2026-10-08T10:00:05+00:00"}
    done = runs.tally("wlt_1", run, sent=3, tasks=tasks)

    assert done["finished"]
    assert done["total_duration_seconds"] == 5.0  # start to the last finish
    assert done["overall_throughput_per_second"] == 0.4  # 2 completed / 5s


def test_a_run_still_sending_is_not_finished_when_its_tasks_are() -> None:
    run = {
        "config": _config(num_tasks=50).model_dump_json(),
        "started_at": "2026-10-08T10:00:00+00:00",
    }
    tasks = [{"status": "completed", "finished_at": "2026-10-08T10:00:01+00:00"}]

    assert not runs.tally("wlt_1", run, sent=1, tasks=tasks)["finished"]


def test_an_unknown_run_reads_as_none() -> None:
    assert asyncio.run(runs.read(FakeRedis(), "wlt_missing")) is None


def test_the_result_is_analysed_once_the_run_finishes(
    monkeypatch: pytest.MonkeyPatch, sent: list[tuple[str, str]]
) -> None:
    from app.services.load_test.worker import service

    redis = FakeRedis()

    async def client() -> FakeRedis:
        return redis

    monkeypatch.setattr(service, "events_redis", client)
    config = _config(num_tasks=2, batch_size=2)
    test_id = asyncio.run(service.LoadTestService.enqueue_load_test(config))

    assert asyncio.run(service.LoadTestService.get_load_test_result(test_id)) is None

    for job_id in ("job-1", "job-2"):
        redis.hashes[f"{_TASK_KEY_PREFIX}{job_id}"] = {
            "status": "completed",
            "finished_at": "2099-01-01T00:00:00+00:00",
        }
    result = asyncio.run(service.LoadTestService.get_load_test_result(test_id))

    assert result is not None and result["status"] == "completed"
    assert result["metrics"]["tasks_completed"] == 2
    assert result["analysis"] is not None


def test_a_finished_run_is_read_once_then_kept(sent: list[tuple[str, str]]) -> None:
    """A finished run's tally is stored with it: the page re-reads it every
    two seconds, and its tasks' records need not be read again."""
    redis = FakeRedis()
    config = _config(num_tasks=2, batch_size=2)
    test_id = asyncio.run(runs.start(redis, config))
    asyncio.run(runs.send(redis, test_id, config))
    for job_id in ("job-1", "job-2"):
        redis.hashes[f"{_TASK_KEY_PREFIX}{job_id}"] = {
            "status": "completed",
            "finished_at": "2099-01-01T00:00:00+00:00",
        }
    first = asyncio.run(runs.read(redis, test_id))
    for job_id in ("job-1", "job-2"):
        del redis.hashes[f"{_TASK_KEY_PREFIX}{job_id}"]  # history expired

    assert first is not None and first["finished"]
    assert asyncio.run(runs.read(redis, test_id)) == first


def test_a_run_that_stopped_sending_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()

    async def refuse(task_name: str, queue: str) -> str:
        raise ConnectionError("redis went away")

    monkeypatch.setattr(runs, "_enqueue", refuse)
    test_id = asyncio.run(runs.start(redis, _config()))
    with pytest.raises(ConnectionError):
        asyncio.run(runs.send(redis, test_id, _config()))

    progress = asyncio.run(runs.read(redis, test_id))
    assert progress is not None and progress["finished"] and not progress["sending"]
    assert "redis went away" in progress["error"]


@pytest.mark.parametrize(
    "config, why",
    [
        (_config(num_tasks=10_001), "10,000"),
        (_config(target_queue="nowhere"), "nowhere"),
    ],
)
def test_a_run_started_in_the_background_is_bounded(
    monkeypatch: pytest.MonkeyPatch, config: LoadTestConfiguration, why: str
) -> None:
    """The API and Overseer start runs that this server sends: capped, and
    only to a queue a worker reads."""
    from app.services.load_test.worker import service

    async def client() -> FakeRedis:
        return FakeRedis()

    monkeypatch.setattr(service, "events_redis", client)
    with pytest.raises(ValueError, match=why):
        asyncio.run(service.LoadTestService.begin_load_test(config))
