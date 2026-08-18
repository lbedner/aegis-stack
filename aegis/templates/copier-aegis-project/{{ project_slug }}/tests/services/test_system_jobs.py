"""Tests for the in-process background job runner."""

import asyncio

import pytest

from app.services.system.jobs import JobHandle, JobRunner


class TestJobRunner:
    @pytest.mark.asyncio
    async def test_a_job_runs_to_done_with_its_result(self) -> None:
        runner = JobRunner()

        async def work(handle: JobHandle) -> dict:
            return {"answer": 42}

        job_id = runner.start("answer", work)
        snapshot = await runner.wait(job_id)

        assert snapshot.status == "done"
        assert snapshot.result == {"answer": 42}
        assert snapshot.error is None

    @pytest.mark.asyncio
    async def test_a_raising_job_fails_with_the_real_error(self) -> None:
        runner = JobRunner()

        async def work(handle: JobHandle) -> dict:
            raise ValueError("QIF import requires a target account_id.")

        job_id = runner.start("import", work)
        snapshot = await runner.wait(job_id)

        assert snapshot.status == "failed"
        assert snapshot.error == "QIF import requires a target account_id."

    @pytest.mark.asyncio
    async def test_subscribers_see_labels_then_the_terminal_event(self) -> None:
        runner = JobRunner()
        release = asyncio.Event()

        async def work(handle: JobHandle) -> dict:
            handle.set_label("step two")
            await release.wait()
            return {"ok": True}

        job_id = runner.start("stepper", work, label="step one")
        queue = runner.subscribe(job_id)
        assert queue is not None

        first = await queue.get()  # primed with the current snapshot
        release.set()
        seen = [first]
        while True:
            item = await asyncio.wait_for(queue.get(), timeout=2)
            if item is None:  # closed after the terminal event
                break
            seen.append(item)

        labels = [snap["label"] for snap in seen]
        assert "step two" in labels
        assert seen[-1]["status"] == "done"
        assert seen[-1]["result"] == {"ok": True}

    @pytest.mark.asyncio
    async def test_a_late_subscriber_still_gets_the_terminal_event(self) -> None:
        runner = JobRunner()

        async def work(handle: JobHandle) -> dict:
            return {"late": True}

        job_id = runner.start("quick", work)
        await runner.wait(job_id)

        queue = runner.subscribe(job_id)
        assert queue is not None
        snapshot = await queue.get()
        assert snapshot["status"] == "done"
        assert await queue.get() is None

    @pytest.mark.asyncio
    async def test_unknown_job_id_has_no_state_and_no_stream(self) -> None:
        runner = JobRunner()
        assert runner.get("nope") is None
        assert runner.subscribe("nope") is None

    @pytest.mark.asyncio
    async def test_finished_jobs_are_evicted_oldest_first(self) -> None:
        runner = JobRunner(max_finished=2)

        async def work(handle: JobHandle) -> dict:
            return {}

        ids = [runner.start(f"j{i}", work) for i in range(3)]
        for job_id in ids:
            await runner.wait(job_id)
        runner.start("j3", work)  # trips eviction

        assert runner.get(ids[0]) is None
        assert runner.get(ids[2]) is not None


class TestSubprocessRunsOffTheEventLoop:
    """pg_dump/psql block for their whole duration; on the loop they
    freeze every other scheduled job (same disease as the import parse,
    fixed the same way)."""

    @staticmethod
    def _fake_run(seen: list):
        import threading

        def fake_run(cmd, **kwargs):
            seen.append(threading.current_thread())

            class _Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return _Result()

        return fake_run

    @pytest.mark.asyncio
    async def test_backup_job_dumps_in_a_thread(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        import threading

        from app.services.system import backup as backup_module

        if not hasattr(backup_module, "subprocess"):
            pytest.skip("sqlite backup copies a file; no subprocess to thread")
        seen: list[threading.Thread] = []
        monkeypatch.setattr(backup_module.subprocess, "run", self._fake_run(seen))
        monkeypatch.chdir(tmp_path)
        await backup_module.backup_database_job()
        assert seen
        assert all(t is not threading.main_thread() for t in seen)

    @pytest.mark.asyncio
    async def test_restore_runs_in_a_thread(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        import threading

        from app.services.system import backup as backup_module

        if not hasattr(backup_module, "subprocess"):
            pytest.skip("sqlite backup copies a file; no subprocess to thread")
        seen: list[threading.Thread] = []
        monkeypatch.setattr(backup_module.subprocess, "run", self._fake_run(seen))
        monkeypatch.chdir(tmp_path)
        backups = tmp_path / "backups"
        backups.mkdir()
        (backups / "b.sql").write_text("-- dump")
        ok = await backup_module.restore_database_from_backup("b.sql")
        assert ok
        assert seen
        assert all(t is not threading.main_thread() for t in seen)
