"""
Tests for scheduler functionality.

Note: The scheduler focuses entirely on system service monitoring.
We test the service functions directly rather than complex scheduler components.

For integration tests of the actual scheduler, see the CLI tests that generate
complete projects and validate they work correctly.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytest

from app.services.system.health import check_system_status


@pytest.mark.asyncio
async def test_scheduler_basic_setup() -> None:
    """Test that the scheduler can be set up and jobs can be added."""
    scheduler = AsyncIOScheduler()

    # Add a simple job
    scheduler.add_job(check_system_status, trigger="interval", minutes=5, id="test_job")

    # Check job was added
    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "test_job"


@pytest.mark.asyncio
async def test_system_service_can_be_scheduled() -> None:
    """Test that our system service functions work with APScheduler."""
    scheduler = AsyncIOScheduler()

    # Test that our system service function can be scheduled without errors
    scheduler.add_job(check_system_status, trigger="interval", seconds=1, id="system")

    assert len(scheduler.get_jobs()) == 1

    # Get job function
    system_job = scheduler.get_job("system")

    assert system_job.func == check_system_status


@pytest.mark.asyncio
async def test_scheduler_heartbeat_job_registered() -> None:
    """The heartbeat job exists and its beacon file gets touched."""
    from app.components.scheduler.heartbeat import (
        HEARTBEAT_FILE,
        HEARTBEAT_JOB_ID,
        touch_scheduler_heartbeat,
    )
    from app.components.scheduler.main import create_scheduler

    scheduler = create_scheduler()
    job = scheduler.get_job(HEARTBEAT_JOB_ID)
    assert job is not None
    assert job.trigger.interval.total_seconds() <= 30

    HEARTBEAT_FILE.unlink(missing_ok=True)
    await touch_scheduler_heartbeat()
    assert HEARTBEAT_FILE.exists()


def test_orphan_sweep_exports_before_deleting(tmp_path, monkeypatch) -> None:
    """#1026: the sweep enforces code-as-truth by deleting persisted jobs
    not registered in code. On the first boot after an update that is
    every schedule ever added at runtime (sector-7g lost 26 in one INFO
    line). Deletion must leave a file the operator can restore from."""
    # A memory-backed scheduler ships neither the sweep nor SQLAlchemy;
    # skip before importing either.
    orphans = pytest.importorskip("app.services.scheduler.orphans")
    pytest.importorskip("sqlalchemy")
    from contextlib import contextmanager
    import json
    import pickle

    from sqlalchemy import create_engine, text
    from sqlmodel import Session

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE apscheduler_jobs (id VARCHAR PRIMARY KEY, "
                "next_run_time FLOAT, job_state BLOB)"
            )
        )
        state = pickle.dumps(
            {
                "func": "app.jobs:morning_donut_run",
                "trigger": "cron[hour=7]",
                "kwargs": {"n": 1},
            }
        )
        conn.execute(
            text("INSERT INTO apscheduler_jobs VALUES ('morning_donut_run', 1.0, :s)"),
            {"s": state},
        )
        conn.execute(
            text("INSERT INTO apscheduler_jobs VALUES ('in_code', 2.0, :s)"),
            {"s": state},
        )

    @contextmanager
    def fake_session(autocommit: bool = True):
        with Session(engine) as session:
            yield session
            session.commit()

    monkeypatch.setattr(orphans, "db_session", fake_session)
    monkeypatch.setattr(orphans.settings, "DATABASE_BACKUP_DIR", str(tmp_path))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_system_status, trigger="interval", minutes=5, id="in_code")

    orphans.drop_unknown_persisted_jobs(scheduler)

    with engine.begin() as conn:
        left = {r[0] for r in conn.execute(text("SELECT id FROM apscheduler_jobs"))}
    assert left == {"in_code"}

    exports = list(tmp_path.glob("orphan_jobs_*.json"))
    assert len(exports) == 1, exports
    rows = json.loads(exports[0].read_text())
    assert rows[0]["id"] == "morning_donut_run"
    assert "morning_donut_run" in rows[0]["func"]
    assert rows[0]["kwargs"] == {"n": 1}


class TestSchedulerHeartbeat:
    """The container healthcheck runs this module, so the path and the
    staleness window live in one place rather than in a compose string."""

    def test_a_fresh_beacon_is_healthy(self, tmp_path, monkeypatch) -> None:
        from app.components.scheduler import heartbeat

        beacon = tmp_path / "beat"
        beacon.touch()
        monkeypatch.setattr(heartbeat, "HEARTBEAT_FILE", beacon)

        assert heartbeat.is_fresh() is True

    def test_a_stale_beacon_is_not(self, tmp_path, monkeypatch) -> None:
        import os
        import time

        from app.components.scheduler import heartbeat

        beacon = tmp_path / "beat"
        beacon.touch()
        old = time.time() - heartbeat.MAX_AGE_SECONDS - 1
        os.utime(beacon, (old, old))
        monkeypatch.setattr(heartbeat, "HEARTBEAT_FILE", beacon)

        assert heartbeat.is_fresh() is False

    def test_a_missing_beacon_is_not(self, tmp_path, monkeypatch) -> None:
        from app.components.scheduler import heartbeat

        monkeypatch.setattr(heartbeat, "HEARTBEAT_FILE", tmp_path / "never-written")

        assert heartbeat.is_fresh() is False

    def test_running_the_module_exits_by_freshness(self, tmp_path, monkeypatch) -> None:
        from app.components.scheduler import heartbeat

        monkeypatch.setattr(heartbeat, "HEARTBEAT_FILE", tmp_path / "never-written")
        with pytest.raises(SystemExit) as stale:
            heartbeat.main()
        assert stale.value.code == 1

        (tmp_path / "never-written").touch()
        with pytest.raises(SystemExit) as fresh:
            heartbeat.main()
        assert fresh.value.code == 0


def _locked_once_store():  # type: ignore[no-untyped-def]
    """A job store whose first write-back fails, as SQLite does under a
    concurrent writer ("database is locked")."""
    from apscheduler.jobstores.memory import MemoryJobStore

    class Store(MemoryJobStore):
        failed = False

        def update_job(self, job) -> None:  # type: ignore[no-untyped-def]
            if not self.failed:
                self.failed = True
                raise RuntimeError("database is locked")
            super().update_job(job)

    return Store()


async def _runs_after_a_locked_write(scheduler_cls: type[AsyncIOScheduler]) -> int:
    import asyncio

    runs: list[int] = []
    scheduler = scheduler_cls(jobstore_retry_interval=0.05)
    scheduler.add_jobstore(_locked_once_store(), "default")
    scheduler.add_job(lambda: runs.append(1), "interval", seconds=0.05)
    scheduler.start()
    await asyncio.sleep(0.5)
    scheduler.shutdown(wait=False)
    return len(runs)


@pytest.mark.asyncio
async def test_a_locked_write_back_does_not_stop_the_scheduler() -> None:
    """APScheduler 3.x lets a failed ``update_job`` escape ``wakeup()``
    before the timer is re-armed: the process lives on, the scheduler
    never wakes again. The plain class documents that; ours keeps firing."""
    from app.components.scheduler.resilient import ResilientScheduler

    assert await _runs_after_a_locked_write(AsyncIOScheduler) <= 1
    assert await _runs_after_a_locked_write(ResilientScheduler) > 2
