"""Jobs that outlive the process that started them.

With a worker in the stack, a job's state lives in Redis so the webserver
that took the request and the worker that does the work agree on one
record, and the jobs API answers for ids it never ran itself.
"""

import asyncio
from typing import Any

import pytest

from app.services.system.job_store import RedisJobStore
from app.services.system.jobs import JobRunner


class FakeRedis:
    """The four calls the store makes, over a dict."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.ttl: dict[str, int] = {}

    async def hset(self, key: str, mapping: dict[str, str]) -> None:
        self.hashes.setdefault(key, {}).update(mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def expire(self, key: str, seconds: int) -> None:
        self.ttl[key] = seconds

    async def aclose(self) -> None:
        return None

    async def scan_iter(self, match: str):
        prefix = match.rstrip("*")
        for key in list(self.hashes):
            if key.startswith(prefix):
                yield key


@pytest.fixture
def store() -> RedisJobStore:
    return RedisJobStore(FakeRedis())


class TestRedisJobStore:
    def test_a_job_is_created_running_and_read_back(self, store) -> None:
        asyncio.run(store.create("j1", "documents-extract:5", "Queued..."))

        snapshot = asyncio.run(store.get("j1"))

        assert snapshot is not None
        assert snapshot.status == "running" and snapshot.label == "Queued..."
        assert snapshot.name == "documents-extract:5"

    def test_labels_then_a_result_land_in_order(self, store) -> None:
        asyncio.run(store.create("j1", "x", "start"))
        asyncio.run(store.set_label("j1", "Reading page 3 of 10..."))
        asyncio.run(store.finish("j1", {"read": 10, "unread": 0, "skipped": 0}))

        snapshot = asyncio.run(store.get("j1"))

        assert snapshot is not None and snapshot.status == "done"
        assert snapshot.result == {"read": 10, "unread": 0, "skipped": 0}
        assert snapshot.label == "Reading page 3 of 10..."

    def test_a_failure_keeps_its_reason(self, store) -> None:
        asyncio.run(store.create("j1", "x", "start"))
        asyncio.run(store.fail("j1", "model not found"))

        snapshot = asyncio.run(store.get("j1"))

        assert snapshot is not None
        assert snapshot.status == "failed" and snapshot.error == "model not found"

    def test_an_unknown_id_is_none(self, store) -> None:
        assert asyncio.run(store.get("nope")) is None

    def test_records_expire_rather_than_pile_up(self, store) -> None:
        asyncio.run(store.create("j1", "x", "start"))
        assert store._redis.ttl["jobs:j1"] > 0


class TestRunnerFallsBackToTheStore:
    def test_get_answers_for_a_remote_job(self, store) -> None:
        runner = JobRunner()
        runner.attach_remote(store)
        asyncio.run(store.create("r1", "remote", "Queued..."))

        assert runner.get("r1") is None  # not local
        snapshot = asyncio.run(runner.lookup("r1"))
        assert snapshot is not None and snapshot.label == "Queued..."

    def test_subscribe_relays_remote_progress_until_terminal(self, store) -> None:
        async def scenario() -> list[Any]:
            runner = JobRunner()
            runner.attach_remote(store, poll_seconds=0.01)
            await store.create("r1", "remote", "Queued...")
            queue = await runner.subscribe_any("r1")
            assert queue is not None
            seen: list[Any] = [await queue.get()]
            await store.set_label("r1", "page 1")
            await store.finish("r1", {"read": 1})
            while True:
                item = await asyncio.wait_for(queue.get(), timeout=2)
                seen.append(item)
                if item is None:
                    break
            return seen

        seen = asyncio.run(scenario())

        assert seen[0]["status"] == "running"
        assert seen[-1] is None
        assert seen[-2]["status"] == "done" and seen[-2]["result"] == {"read": 1}

    def test_unknown_everywhere_is_none(self, store) -> None:
        runner = JobRunner()
        runner.attach_remote(store)
        assert asyncio.run(runner.lookup("ghost")) is None
        assert asyncio.run(runner.subscribe_any("ghost")) is None


class TestListingEveryJob:
    def test_the_store_lists_what_it_holds(self, store) -> None:
        asyncio.run(store.create("a", "documents-extract:1", "Queued..."))
        asyncio.run(store.create("b", "documents-extract:2", "Queued..."))

        listed = asyncio.run(store.list_jobs())

        assert {j.job_id for j in listed} == {"a", "b"}
        assert all(j.started_at for j in listed)

    def test_the_runner_merges_local_and_remote_newest_first(self, store) -> None:
        async def scenario() -> list[str]:
            runner = JobRunner()
            runner.attach_remote(store)
            await store.create("remote", "documents-extract:9", "Queued...")

            async def work(handle: Any) -> dict[str, int]:
                return {"ok": 1}

            local = runner.start("documents-extract:1", work)
            await runner.wait(local)
            return [j.job_id for j in await runner.list_all()]

        ids = asyncio.run(scenario())

        assert ids[0] == ids[0] and set(ids) == {
            "remote",
            ids[0] if ids[0] != "remote" else ids[1],
        }
        assert len(ids) == 2

    def test_subscribe_all_sees_a_new_local_job_and_its_end(self, store) -> None:
        async def scenario() -> list[Any]:
            runner = JobRunner()
            runner.attach_remote(store, poll_seconds=0.01)
            queue = runner.subscribe_all()

            async def work(handle: Any) -> dict[str, int]:
                handle.set_label("page 1 of 1")
                return {"read": 1}

            job_id = runner.start("documents-extract:1", work)
            await runner.wait(job_id)
            seen = []
            while not queue.empty():
                seen.append(queue.get_nowait())
            runner.unsubscribe_all(queue)
            return seen

        seen = asyncio.run(scenario())

        assert [s["status"] for s in seen][0] == "running"
        assert seen[-1]["status"] == "done" and seen[-1]["result"] == {"read": 1}
        assert any(s["label"] == "page 1 of 1" for s in seen)

    def test_subscribe_all_relays_remote_changes(self, store) -> None:
        async def scenario() -> list[Any]:
            runner = JobRunner()
            runner.attach_remote(store, poll_seconds=0.01)
            queue = runner.subscribe_all()
            await store.create("r", "documents-extract:3", "Queued...")
            await store.set_label("r", "page 2 of 5")
            await asyncio.sleep(0.05)
            await store.finish("r", {"read": 5})
            await asyncio.sleep(0.05)
            seen = []
            while not queue.empty():
                seen.append(queue.get_nowait())
            runner.unsubscribe_all(queue)
            return seen

        seen = asyncio.run(scenario())

        assert seen and seen[-1]["job_id"] == "r" and seen[-1]["status"] == "done"


class TestAStoreThatIsDown:
    def test_listing_degrades_to_local_jobs(self) -> None:
        class Down:
            async def list_jobs(self):
                raise ConnectionError("redis is away")

            async def get(self, job_id: str):
                raise ConnectionError("redis is away")

        async def scenario() -> tuple[int, Any]:
            runner = JobRunner()
            runner.attach_remote(Down())

            async def work(handle: Any) -> dict[str, int]:
                return {}

            job_id = runner.start("documents-extract:1", work)
            await runner.wait(job_id)
            return len(await runner.list_all()), await runner.lookup("ghost")

        count, ghost = asyncio.run(scenario())

        assert count == 1 and ghost is None
